// Serves app/ on :3000 and proxies /rpc -> validator RPC (8899) and /ws -> websocket (8900),
// so the page needs only one forwarded port in Codespaces.
const http = require('http'), net = require('net'), fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, 'app');
const TYPES = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0];
  if (url === '/rpc') {
    const up = http.request({ host: '127.0.0.1', port: 8899, path: '/', method: req.method,
      headers: { 'content-type': 'application/json' } }, r => { res.writeHead(r.statusCode, { 'content-type': 'application/json' }); r.pipe(res); });
    up.on('error', () => { res.writeHead(502); res.end('validator not running'); });
    return req.pipe(up);
  }
  const file = path.join(ROOT, path.normalize(url === '/' ? '/index.html' : url));
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end(); }
  fs.readFile(file, (e, d) => {
    if (e) { res.writeHead(404); return res.end('not found'); }
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream' }); res.end(d);
  });
});
server.on('upgrade', (req, sock, head) => {
  if (!req.url.startsWith('/ws')) return sock.destroy();
  const up = net.connect(8900, '127.0.0.1', () => {
    let h = `GET / HTTP/1.1\r\n`;
    for (let i = 0; i < req.rawHeaders.length; i += 2) {
      const k = req.rawHeaders[i];
      h += `${k}: ${k.toLowerCase() === 'host' ? '127.0.0.1:8900' : req.rawHeaders[i + 1]}\r\n`;
    }
    up.write(h + '\r\n'); if (head && head.length) up.write(head);
    sock.pipe(up).pipe(sock);
  });
  up.on('error', () => sock.destroy()); sock.on('error', () => up.destroy());
});
server.listen(3000, () => console.log('Pagina pronta sulla porta 3000 (apri il link con ?rpc=proxy)'));
