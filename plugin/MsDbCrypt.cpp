/*
 * MsDbCrypt — open-source Firebird 4 database-encryption plugin that reproduces
 * MailStore Home's "DBCRYPT" page cipher, so stock Firebird opens a MailStore
 * archive database in place, read-only, on any platform.
 *
 * Scheme (reverse-engineered, see pcr20/mailstore-tools):
 *   contentKey = DecryptAES(masterKey, encryptionKey) from the sibling .key file
 *     DecryptAES: aesKey = PBKDF2-HMAC-SHA1(key, salt=blob[0:16], 1000, 32);
 *                 AES-256-CBC(aesKey, iv=blob[16:32]).decrypt(blob[32:]) -> [salt|data]
 *   page encrypt/decrypt = AES-256-ECB(contentKey) over the buffer Firebird passes.
 *
 * The plugin reads the content key from the MailStore .key file sitting next to
 * the database (same basename, .key extension). No Windows / DPAPI needed —
 * the masterkey is stored in the clear.
 *
 * Build: g++ -shared -fPIC -I<fb>/include MsDbCrypt.cpp -o DBCRYPT.so -lcrypto
 * Register in plugins.conf:  Plugin = DBCRYPT { Module = $(dir_plugins)/DBCRYPT }
 */
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <atomic>
#include <firebird/Interface.h>
#include <openssl/evp.h>
#include <openssl/sha.h>

using namespace Firebird;
typedef std::atomic_int FbSampleAtomic;

static IMaster* master = NULL;

namespace {

// ---- minimal helpers -------------------------------------------------------

// extract keys.<obj>.key base64 from the .key JSON (field order is mode,key,...)
static bool jsonKeyB64(const char* buf, const char* obj, char* out, size_t outsz)
{
	const char* p = strstr(buf, obj);
	if (!p) return false;
	p = strstr(p, "\"key\"");
	if (!p) return false;
	p = strchr(p + 5, ':');     if (!p) return false;
	p = strchr(p, '"');         if (!p) return false;
	p++;
	const char* e = strchr(p, '"'); if (!e) return false;
	size_t n = (size_t)(e - p);
	if (n >= outsz) return false;
	memcpy(out, p, n); out[n] = 0;
	return true;
}

static int b64dec(const char* in, unsigned char* out)
{
	// standard base64; returns decoded length
	int len = EVP_DecodeBlock(out, (const unsigned char*)in, (int)strlen(in));
	if (len < 0) return -1;
	// EVP_DecodeBlock pads output to a multiple of 3; adjust for '=' padding
	size_t l = strlen(in);
	if (l >= 1 && in[l-1] == '=') len--;
	if (l >= 2 && in[l-2] == '=') len--;
	return len;
}

static bool aesCbcDecrypt(const unsigned char* key, const unsigned char* iv,
	const unsigned char* ct, int ctlen, unsigned char* out)
{
	EVP_CIPHER_CTX* c = EVP_CIPHER_CTX_new();
	if (!c) return false;
	int ol = 0, tl = 0; bool ok = false;
	if (EVP_DecryptInit_ex(c, EVP_aes_256_cbc(), NULL, key, iv) == 1 &&
		EVP_CIPHER_CTX_set_padding(c, 0) == 1 &&
		EVP_DecryptUpdate(c, out, &ol, ct, ctlen) == 1 &&
		EVP_DecryptFinal_ex(c, out + ol, &tl) == 1)
		ok = true;
	EVP_CIPHER_CTX_free(c);
	return ok;
}

static bool aesEcb(const unsigned char* key, bool enc,
	const unsigned char* in, unsigned len, unsigned char* out)
{
	EVP_CIPHER_CTX* c = EVP_CIPHER_CTX_new();
	if (!c) return false;
	int ol = 0, tl = 0; bool ok = false;
	if (EVP_CipherInit_ex(c, EVP_aes_256_ecb(), NULL, key, NULL, enc ? 1 : 0) == 1 &&
		EVP_CIPHER_CTX_set_padding(c, 0) == 1 &&
		EVP_CipherUpdate(c, out, &ol, in, (int)len) == 1 &&
		EVP_CipherFinal_ex(c, out + ol, &tl) == 1)
		ok = true;
	EVP_CIPHER_CTX_free(c);
	return ok;
}

// ---- plugin module ---------------------------------------------------------

class PluginModule : public IPluginModuleImpl<PluginModule, CheckStatusWrapper>
{
public:
	PluginModule() : pluginManager(NULL) {}
	~PluginModule() { if (pluginManager) { pluginManager->unregisterModule(this); } }
	void registerMe(IPluginManager* m) { pluginManager = m; m->registerModule(this); }
	void doClean() { pluginManager = NULL; }
	void threadDetach() {}
private:
	IPluginManager* pluginManager;
};

class DbCrypt : public IDbCryptPluginImpl<DbCrypt, CheckStatusWrapper>
{
public:
	explicit DbCrypt(IPluginConfig* cnf) : config(cnf), haveKey(false), refCounter(0), owner(NULL)
	{ config->addRef(); dbPath[0] = 0; }
	~DbCrypt() { config->release(); }

	void encrypt(CheckStatusWrapper* status, unsigned length, const void* from, void* to);
	void decrypt(CheckStatusWrapper* status, unsigned length, const void* from, void* to);
	void setKey(CheckStatusWrapper* status, unsigned length, IKeyHolderPlugin** sources, const char* keyName);

	void setInfo(CheckStatusWrapper* status, IDbCryptInfo* info)
	{
		const char* p = info->getDatabaseFullPath(status);
		if (p) { strncpy(dbPath, p, sizeof(dbPath)-1); dbPath[sizeof(dbPath)-1]=0; }
	}

	int release() { if (--refCounter == 0) { delete this; return 0; } return 1; }
	void addRef() { ++refCounter; }
	void setOwner(IReferenceCounted* o) { owner = o; }
	IReferenceCounted* getOwner() { return owner; }

private:
	IPluginConfig* config;
	bool haveKey;
	unsigned char contentKey[32];
	char dbPath[1024];
	FbSampleAtomic refCounter;
	IReferenceCounted* owner;
	void err(CheckStatusWrapper* status, const char* msg);
	bool loadContentKey();
};

void DbCrypt::err(CheckStatusWrapper* status, const char* msg)
{
	static char buf[200]; strncpy(buf, msg, sizeof(buf)-1); buf[sizeof(buf)-1]=0;
	ISC_STATUS_ARRAY v;
	v[0]=isc_arg_gds; v[1]=isc_random; v[2]=isc_arg_string; v[3]=(ISC_STATUS)buf; v[4]=isc_arg_end;
	status->setErrors(v);
}

bool DbCrypt::loadContentKey()
{
	// derive sibling .key path
	char kp[1100]; strncpy(kp, dbPath, sizeof(kp)-1); kp[sizeof(kp)-1]=0;
	size_t L = strlen(kp);
	if (L > 4 && strcasecmp(kp + L - 4, ".fdb") == 0) strcpy(kp + L - 4, ".key");
	else strncat(kp, ".key", sizeof(kp)-L-1);

	FILE* f = fopen(kp, "rb");
	if (!f) return false;
	static char js[65536]; size_t n = fread(js, 1, sizeof(js)-1, f); fclose(f); js[n]=0;
	// strip UTF-8 BOM
	char* p = js; if (n>=3 && (unsigned char)p[0]==0xEF && (unsigned char)p[1]==0xBB && (unsigned char)p[2]==0xBF) p+=3;

	char mkb64[512], ekb64[512];
	if (!jsonKeyB64(p, "\"masterkey\"", mkb64, sizeof(mkb64))) return false;
	if (!jsonKeyB64(p, "\"encryptionkey\"", ekb64, sizeof(ekb64))) return false;
	unsigned char mk[256], ek[512];
	int mkl = b64dec(mkb64, mk); int ekl = b64dec(ekb64, ek);
	if (mkl != 32 || ekl < 48 || ((ekl-32) % 16) != 0) return false;

	unsigned char dk[32];
	if (PKCS5_PBKDF2_HMAC_SHA1((const char*)mk, 32, ek, 16, 1000, 32, dk) != 1) return false;
	unsigned char plain[512];
	if (!aesCbcDecrypt(dk, ek + 16, ek + 32, ekl - 32, plain)) return false;
	// plain = [salt(16) | contentKey(32) | ...]; verify salt echoes blob salt
	memcpy(contentKey, plain + 16, 32);
	haveKey = true;
	return true;
}

void DbCrypt::setKey(CheckStatusWrapper* status, unsigned, IKeyHolderPlugin**, const char*)
{
	status->init();
	if (haveKey) return;
	if (!loadContentKey())
		err(status, "MsDbCrypt: cannot load MailStore content key (sibling .key file)");
}

void DbCrypt::encrypt(CheckStatusWrapper* status, unsigned length, const void* from, void* to)
{
	status->init();
	if (!haveKey) { err(status, "MsDbCrypt: key not set"); return; }
	if (!aesEcb(contentKey, true, (const unsigned char*)from, length, (unsigned char*)to))
		err(status, "MsDbCrypt: encrypt failed");
}

void DbCrypt::decrypt(CheckStatusWrapper* status, unsigned length, const void* from, void* to)
{
	status->init();
	if (!haveKey) { err(status, "MsDbCrypt: key not set"); return; }
	if (!aesEcb(contentKey, false, (const unsigned char*)from, length, (unsigned char*)to))
		err(status, "MsDbCrypt: decrypt failed");
}

class Factory : public IPluginFactoryImpl<Factory, CheckStatusWrapper>
{
public:
	IPluginBase* createPlugin(CheckStatusWrapper*, IPluginConfig* fp)
	{ DbCrypt* p = new DbCrypt(fp); p->addRef(); return p; }
};

PluginModule module;
Factory factory;

} // namespace

extern "C" FB_DLL_EXPORT void FB_PLUGIN_ENTRY_POINT(IMaster* m)
{
	master = m;
	IPluginManager* pm = m->getPluginManager();
	module.registerMe(pm);
	pm->registerPluginFactory(IPluginManager::TYPE_DB_CRYPT, "DBCRYPT", &factory);
}
