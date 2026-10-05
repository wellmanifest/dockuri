#!/usr/bin/env node
/**
 * Reference Node.js Worker Daemon for Dockuri (DOCK-STD-001).
 * Listens on Unix Domain Socket, executes procedures with zero cold-start.
 */

const net = require('net');
const fs = require('fs');
const readline = require('readline');

const SOCKET_PATH = process.env.DOCKURI_SOCKET || '/tmp/dockuri_node_ref.sock';

const REGISTRY = {
  'string.slugify': ({ text }) => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
  'math.multiply': ({ a, b }) => a * b
};

if (fs.existsSync(SOCKET_PATH)) {
  try { fs.unlinkSync(SOCKET_PATH); } catch (e) {}
}

const server = net.createServer((socket) => {
  const rl = readline.createInterface({ input: socket });
  rl.on('line', (line) => {
    const t0 = process.hrtime.bigint();
    let req;
    try {
      req = JSON.parse(line);
    } catch (e) {
      socket.write(JSON.stringify({ ok: false, error: 'Invalid JSON' }) + '\n');
      return;
    }

    const { id = 'unknown', proc, args = {} } = req;
    let result = null;
    let error = null;

    if (proc === '__ping__') {
      result = { status: 'pong', runtime: `node-${process.version}`, pid: process.pid };
    } else if (REGISTRY[proc]) {
      try {
        result = REGISTRY[proc](args);
      } catch (err) {
        error = err.message;
      }
    } else {
      error = `Procedure not found: ${proc}`;
    }

    const t1 = process.hrtime.bigint();
    const duration_us = Number((t1 - t0) / 1000n);

    socket.write(JSON.stringify({
      id,
      ok: error === null,
      result,
      error,
      metrics: { duration_us }
    }) + '\n');
  });
});

server.listen(SOCKET_PATH, () => {
  fs.chmodSync(SOCKET_PATH, 0o660);
  console.log(`✓ Dockuri Node.js Worker ready on UDS: ${SOCKET_PATH} (PID ${process.pid})`);
});

process.on('SIGINT', () => { server.close(); process.exit(0); });
process.on('SIGTERM', () => { server.close(); process.exit(0); });
