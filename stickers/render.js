const { chromium } = require('playwright');
const fs = require('fs');
const OUT = '/home/user/orangeorangusbot/stickers/';
const IMG = 'data:image/jpeg;base64,' + fs.readFileSync(__dirname + '/mascot-source.jpg').toString('base64');
const L = '268,120 346,129 343,182 278,183', R = '371,141 441,153 433,211 378,206';
const lens = (fill) => `<polygon points="${L}" fill="${fill}" stroke-linejoin="round" stroke-width="8" stroke="${fill}"/><polygon points="${R}" fill="${fill}" stroke-linejoin="round" stroke-width="8" stroke="${fill}"/>`;
const at = (pts, svg) => { const p = pts.split(' ').map(s => s.split(',').map(Number)); const cx = p.reduce((a, q) => a + q[0], 0) / 4, cy = p.reduce((a, q) => a + q[1], 0) / 4; return `<g transform="translate(${cx} ${cy})">${svg}</g>`; };
const both = (svg) => at(L, svg) + at(R, svg);
const heart = `<path d="M0 22 C-40 -6 -24 -34 0 -16 C24 -34 40 -6 0 22Z" fill="#ff2d6f" stroke="#fff" stroke-width="3"/>`;
const flame = `<path d="M0 26 C-26 20 -24 -4 -8 -18 C-6 -6 0 -6 2 -30 C18 -16 28 4 16 22 C10 28 4 28 0 26Z" fill="#ffb300"/><path d="M0 24 C-12 20 -12 6 -2 -4 C0 4 6 4 6 -8 C14 2 14 18 0 24Z" fill="#ff3d00"/>`;
const sun = `<circle r="16" fill="#ffe14d"/><g stroke="#ffe14d" stroke-width="5" stroke-linecap="round">${[0,45,90,135,180,225,270,315].map(a=>`<line x1="0" y1="-22" x2="0" y2="-30" transform="rotate(${a})"/>`).join('')}</g>`;
const txt = (t, y, size, color = '#ffd23f', rot = -4) => `<text x="256" y="${y}" text-anchor="middle" transform="rotate(${rot} 256 ${y})" font-family="Inter Display" font-weight="900" font-style="italic" font-size="${size}" fill="${color}" stroke="#2a1205" stroke-width="${size/5}" paint-order="stroke" stroke-linejoin="round">${t}</text>`;
const lines = (side) => `<g stroke="#fff" stroke-width="9" stroke-linecap="round" opacity=".95">${side.map(([x1,y1,x2,y2])=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#2a1205" stroke-width="17"/><line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`).join('')}</g>`;
const S = [
  { f: 'og-badge', rot: -6, scale: .80, ty: -34, eyes: lens('#ffcf33') + both(`<text y="12" text-anchor="middle" font-family="Inter Display" font-weight="900" font-size="34" fill="#7a3d00">OG</text>`),
    top: '', bottom: txt('OG PEELER', 470, 74) + txt('FIRST 500 ONLY', 506, 30, '#fff', -4) },
  { f: 'og-cool', z: 1.75, cx: 350, cy: 190, rot: 10, scale: .80, ty: -30, eyes: lens('#ff2d6f22') + both(heart),
    top: lines([[40,120,80,150],[30,200,70,205],[472,120,432,150],[482,200,442,205]]), bottom: txt('EARLY = OG', 476, 72) },
  { f: 'peel-the-hype', z: 1.4, cx: 320, cy: 222, rot: -12, scale: .78, ty: -36, eyes: lens('#2a0a00') + both(flame),
    top: txt('LFG', 70, 64, '#ff5a1f', 8), bottom: txt('PEEL THE HYPE', 476, 60) },
  { f: 'gm', cx: 345, rot: 4, scale: .80, ty: -30, eyes: lens('#ff9d2e') + both(sun),
    top: '', bottom: txt('GM TROOP', 474, 80, '#ffe14d') },
  { f: 'still-peeling', rot: -3, scale: .76, ty: -40, shake: true, eyes: lens('#1a1a1a') + both(`<text y="10" text-anchor="middle" font-family="Inter Display" font-weight="900" font-size="26" fill="#39ff14">500</text>`),
    top: lines([[30,160,60,170],[24,240,58,240],[482,160,452,170],[488,240,454,240]]), bottom: txt('500 INCOMING', 470, 62) + txt('KEEP SHARING 🍊', 506, 30, '#fff') },
  { f: 'not-in-this-jungle', z: 1.8, cx: 355, cy: 175, rot: 14, scale: .78, ty: -34, eyes: lens('#e00000') + both(`<circle r="9" fill="#fff"/>`) + `<g stroke="#ff1a1a" stroke-width="9" stroke-linecap="round" opacity=".85"><line x1="306" y1="152" x2="0" y2="20"/><line x1="406" y1="176" x2="640" y2="40"/></g>`,
    top: txt('FOMO', 66, 70, '#ff3b3b', 6), bottom: txt('DON\'T FADE THE APE', 474, 48) },
];
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const p = await b.newPage({ viewport: { width: 512, height: 512 } });
  for (const s of S) {
    const disc = `<svg viewBox="0 0 640 640" width="512" height="512"><defs><clipPath id="c"><circle cx="320" cy="320" r="318"/></clipPath></defs><g clip-path="url(#c)"><g transform="translate(320 320) scale(${s.z||1.5}) translate(${-(s.cx||335)} ${-(s.cy||215)})"><image href="${IMG}" width="640" height="640"/>${s.eyes}</g></g><circle cx="320" cy="320" r="314" fill="none" stroke="#fff" stroke-width="10"/></svg>`;
    const tf = `translate(0px,${s.ty}px) rotate(${s.rot}deg) scale(${s.flip ? -s.scale : s.scale},${s.scale})`;
    await p.setContent(`<html><body style="margin:0;background:transparent"><div style="position:relative;width:512px;height:512px">
      <div style="position:absolute;inset:0;transform:${tf};filter:drop-shadow(0 6px 6px rgba(0,0,0,.45))">${disc}</div>
      <svg style="position:absolute;inset:0" width="512" height="512">${s.top}${s.bottom}</svg></div></body></html>`);
    await p.screenshot({ path: OUT + s.f + '.png', omitBackground: true });
  }
  await b.close();
})();
