// Usage: node scripts/verify_step59_public_mode_ui.cjs web/index.html
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('async function validatePublicUpload(file) {');
const end = source.indexOf('\npublicModeStatus().catch', start);
assert(start > 0 && end > start);
let token = '', reads = 0;
let mode = {public_access: true, max_upload_bytes: 500000000, remaining_inspections: 1};
const sandbox = {document: {getElementById: () => ({value: token})},
                 publicModeStatus: async () => {reads++; if (mode instanceof Error) throw mode; return mode;}};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end), sandbox);
(async () => {
  await sandbox.validatePublicUpload({size: 500000000});
  await assert.rejects(sandbox.validatePublicUpload({size: 500000001}), /500 MB/);
  mode = {...mode, remaining_inspections: 0};
  await assert.rejects(sandbox.validatePublicUpload({size: 1}), /quota/);
  mode = {public_access: false};
  await sandbox.validatePublicUpload({size: 500000001});
  mode = new Error('settings unavailable');
  await assert.rejects(sandbox.validatePublicUpload({size: 1}), /settings unavailable/);
  token = 'local-operator-placeholder';
  const previous = reads;
  await sandbox.validatePublicUpload({size: 500000001});
  assert.equal(reads, previous);
  console.log('PASS: 6 public upload UI checks; size, quota, closed mode, settings failure, and operator bypass.');
})().catch(error => {console.error(error);process.exitCode = 1;});
