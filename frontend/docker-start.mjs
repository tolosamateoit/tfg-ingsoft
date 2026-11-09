// Mantiene local la conexión que recibe Vite para los accesos rápidos.
import { createServer, connect } from 'node:net';
import { spawn } from 'node:child_process';

const vite = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5174'], { stdio: 'inherit' });
const server = createServer((client) => {
  const target = connect(5174, '127.0.0.1');
  client.on('error', () => target.destroy());
  target.on('error', () => client.destroy());
  client.pipe(target).pipe(client);
});
server.on('error', (error) => { console.error(error); vite.kill(); process.exitCode = 1; });
server.listen(5173, '0.0.0.0');
vite.on('exit', (code) => { server.close(); process.exitCode = code ?? 1; });
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { vite.kill(signal); server.close(); });
