'use strict';
// Onde está o projeto da interface (Ionic/Angular): a pasta foi renomeada de `frontend` para `web`; aceita as duas.
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');

function webDir() {
  for (const name of ['web', 'frontend']) {
    const dir = path.join(root, name);
    if (fs.existsSync(path.join(dir, 'angular.json'))) return dir;
  }
  return null;
}

module.exports = { root, webDir };
