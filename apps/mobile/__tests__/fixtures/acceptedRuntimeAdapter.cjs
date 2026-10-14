// Bounded subprocess-only native substitutes for accepted desktop controls; not Expo/native durability.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { DatabaseSync, backup } = require('node:sqlite');
const Module = require('node:module');
const source = path.resolve(__dirname, '../../../..');
const ts = require('typescript');
require.extensions['.ts'] = function(mod, filename) {
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }
  }).outputText;
  mod._compile(code, filename);
};
class DB {
  constructor(file) { this.file = file; this.native = new DatabaseSync(file); }
  async execAsync(sql) { this.native.exec(sql); }
  async getFirstAsync(sql, args=[]) { return this.native.prepare(sql).get(...args) ?? null; }
  async getAllAsync(sql, args=[]) { return this.native.prepare(sql).all(...args); }
  async runAsync(sql, args=[]) { return this.native.prepare(sql).run(...args); }
  async closeAsync() { this.native.close(); }
  async withExclusiveTransactionAsync(fn) {
    const tx = new DB(this.file);
    tx.native.exec('BEGIN');
    try { await fn(tx); tx.native.exec('COMMIT'); }
    catch(e) { try { tx.native.exec('ROLLBACK'); } catch {} throw e; }
    finally { await tx.closeAsync(); }
  }
}
let directory;
const storage = new Map();
class File {
  constructor(...parts) { this.uri = path.join(...parts.map(x => typeof x === 'string' ? x : x.uri)); }
  get exists() { return fs.existsSync(this.uri); }
  async copy(dest) { fs.copyFileSync(this.uri, dest.uri); }
  async move(dest) { fs.renameSync(this.uri, dest.uri); this.uri = dest.uri; }
  async delete() { fs.unlinkSync(this.uri); }
}
const load = Module._load;
Module._load = function(id, ...args) {
  if (id === 'expo-crypto') return {
    randomUUID: crypto.randomUUID,
    CryptoDigestAlgorithm: {SHA256:'SHA-256',SHA1:'SHA-1'},
    digest: async (algorithm, bytes) => { const b = crypto.createHash(algorithm === 'SHA-1' ? 'sha1' : 'sha256').update(Buffer.from(bytes)).digest(); return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength); },
    digestStringAsync: async (_, s) => crypto.createHash('sha256').update(s).digest('hex')
  };
  if (id === 'expo-file-system') return {File};
  if (id === '@react-native-async-storage/async-storage') return {
    getItem: async k => storage.get(k) ?? null,
    setItem: async (k,v) => storage.set(k,v)
  };
  if (id === 'expo-sqlite') return {
    defaultDatabaseDirectory: directory,
    openDatabaseAsync: async (name, options, dir) => new DB(path.join(dir ?? directory, name)),
    deleteDatabaseAsync: async (name, dir) => { for (const s of ['', '-wal', '-shm']) fs.rmSync(path.join(dir ?? directory,name+s),{force:true}); },
    backupDatabaseAsync: async ({sourceDatabase, destDatabase}) => {
      // SQLite online backup into the existing destination file, after releasing
      // its idle connection. Mirrors copy contents, not native Expo connection semantics.
      await destDatabase.closeAsync();
      await backup(sourceDatabase.native, destDatabase.file);
      destDatabase.native = new DatabaseSync(destDatabase.file);
    }
  };
  return load.call(this,id,...args);
};
module.exports = {DB, source, setDirectory: dir => { directory=dir; fs.mkdirSync(dir,{recursive:true}); }, req: p => require(path.join(source,'apps/mobile/src',p))};
