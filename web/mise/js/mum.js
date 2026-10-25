// Mum: the cooking teacher who stands over the camera in cook mode.
// She's always a little alive (breathing, blinking), her mouth follows the voice while Mise talks,
// and she hops when a new step starts. Illustrations: web/mise/mums/*.png (flat cutouts); FACES holds
// where the eyes and mouth are in the original 1:1 cutout pixels, so lids and mouth can be drawn on top.

export const MUMS = [
  { id: "indian", label: "Indian", hi: "Beta" },
  { id: "italian", label: "Italian", hi: "Tesoro" },
  { id: "japanese", label: "Japanese", hi: "Ne" },
  { id: "chinese", label: "Chinese", hi: "Bǎobèi" },
  { id: "mexican", label: "Mexican", hi: "Mija" },
  { id: "american", label: "American", hi: "Honey" },
];

const FACES = {
  indian: { w: 218, h: 659, eyeL: [88.1, 96.6], eyeR: [135.0, 96.6], eyeW: 15.0, eyeH: 16.0, mouth: [111.6, 120.0], eyeDist: 46.9, skin: "#de9c73" },
  italian: { w: 265, h: 649, eyeL: [100.5, 101.0], eyeR: [150.1, 96.8], eyeW: 14.5, eyeH: 15.5, mouth: [125.3, 123.7], eyeDist: 49.6, skin: "#eb9d6a" },
  japanese: { w: 193, h: 653, eyeL: [80.1, 101.1], eyeR: [127.4, 100.2], eyeW: 14.5, eyeH: 15.0, mouth: [103.8, 124.3], eyeDist: 47.3, skin: "#fac09a" },
  chinese: { w: 222, h: 668, eyeL: [77.7, 130.1], eyeR: [124.5, 130.3], eyeW: 14.0, eyeH: 15.0, mouth: [101.1, 153.6], eyeDist: 46.9, skin: "#f9b686" },
  mexican: { w: 295, h: 643, eyeL: [114.9, 96.2], eyeR: [163.4, 91.9], eyeW: 14.5, eyeH: 15.0, mouth: [139.1, 118.3], eyeDist: 48.6, skin: "#ee9964" },
  american: { w: 225, h: 678, eyeL: [79.4, 132.6], eyeR: [126.8, 132.2], eyeW: 14.5, eyeH: 15.5, mouth: [103.1, 156.1], eyeDist: 47.3, skin: "#f9b686" },
};

export function savedMum() {
  try { const id = localStorage.getItem("mise:mum"); if (FACES[id]) return id; } catch {}
  return "indian";
}

// Mount a mum into `el`. `speaker` is app.speaker (speaking flag + level() meter).
export function mountMum(el, speaker, { id = savedMum(), height = 300 } = {}) {
  let alive = true, open = 0, blinkT, mouthT;
  const body = document.createElement("div");
  body.className = "mum-body";
  el.replaceChildren(body);

  function build() {
    const f = FACES[id], s = height / f.h;
    el.style.width = `${f.w * s}px`;
    el.style.height = `${height}px`;
    const lid = (e) => `<i class="mum-lid" style="left:${(e[0] - f.eyeW / 2 - 2.5) * s}px;top:${(e[1] - f.eyeH / 2 - 2.5) * s}px;`
      + `width:${(f.eyeW + 5) * s}px;height:${(f.eyeH + 5) * s}px;background:${f.skin}"></i>`;
    const m = MUMS.find((x) => x.id === id);
    body.innerHTML = `<img src="/mise/mums/${id}.png" alt="${m.label} mum" draggable="false">${lid(f.eyeL)}${lid(f.eyeR)}`
      + `<i class="mum-mouth" style="left:${f.mouth[0] * s}px;top:${f.mouth[1] * s}px;width:${f.eyeDist * 0.42 * s}px"></i>`;
    body.dataset.s = s;
    el.dataset.mum = id;
  }

  function blink() {
    if (!alive) return;
    body.classList.add("blink");
    setTimeout(() => body.classList.remove("blink"), 130);
    if (Math.random() < 0.25) setTimeout(() => { body.classList.add("blink"); setTimeout(() => body.classList.remove("blink"), 120); }, 260);
    blinkT = setTimeout(blink, 2200 + Math.random() * 2600);
  }

  function mouth() {
    if (!alive) return;
    const talking = !!speaker?.speaking;
    let target = 0;
    if (talking) {
      const lv = speaker.level?.();
      // hub voice: follow its loudness; browser voice (no meter): a natural-looking flap
      target = lv == null ? (Math.random() < 0.2 ? 0.15 : 0.45 + Math.random() * 0.55) : Math.min(1, lv * 1.4);
    }
    open += (target - open) * 0.55;
    const f = FACES[id], s = +body.dataset.s, mEl = body.querySelector(".mum-mouth");
    if (mEl) mEl.style.height = `${open < 0.06 ? 0 : open * f.eyeDist * 0.3 * s}px`;
    el.classList.toggle("talking", talking);
    mouthT = setTimeout(mouth, 70);
  }

  build();
  blink();
  mouth();
  return {
    get id() { return id; },
    hello() { return MUMS.find((x) => x.id === id).hi; },
    set(newId) {
      if (!FACES[newId]) return;
      id = newId;
      try { localStorage.setItem("mise:mum", id); } catch {}
      build();
      this.hop();
    },
    hop() { el.classList.remove("hop"); void el.offsetWidth; el.classList.add("hop"); },
    destroy() { alive = false; clearTimeout(blinkT); clearTimeout(mouthT); el.replaceChildren(); },
  };
}
