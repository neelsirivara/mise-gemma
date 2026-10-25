// Little looping scenes for cook mode, one per kind of action (cut, crack, stir, fry, simmer).
// Drawn in SVG with CSS animation, so they work offline. sceneFor() picks one from the step's
// words; steps that match nothing (plating, resting…) show no scene.
const O = "#3b2a22"; // bold cartoon outline

const RULES = [
  ["crack", /\bcrack/i],
  ["simmer", /\b(simmer|boil|lid on|cover|steam|poach|braise|reduce)/i],
  ["fry", /\b(fry|fried|saut[eé]|sear|brown|toast|skillet|pan\b|heat (the )?(oil|butter))/i],
  ["cut", /\b(chop|slice|dice|cut|mince|halve|peel|grate|trim|quarter)/i],
  ["stir", /\b(stir|mix|whisk|combine|toss|fold|beat|mash|blend)/i],
];
export const VERB = { cut: "Cut!", crack: "Crack!", stir: "Stir!", fry: "Fry!", simmer: "Simmer" };
export function sceneFor(text = "") {
  for (const [kind, re] of RULES) if (re.test(text)) return kind;
  return null;
}

export const SCENES = {
  cut: `<svg viewBox="0 0 340 190" aria-hidden="true"><style>
    .sc-cut-knife{transform-origin:250px 40px;animation:sc-cut-chop .42s ease-in-out infinite}
    @keyframes sc-cut-chop{0%,100%{transform:translateY(-34px) rotate(-8deg)}45%{transform:translateY(8px) rotate(0)}}
    .sc-cut-carrot{animation:sc-cut-feed 1.68s steps(4) infinite}@keyframes sc-cut-feed{to{transform:translateX(-56px)}}
    .sc-cut-sl{opacity:0;animation:sc-cut-slice 1.68s infinite}.sc-cut-s2{animation-delay:.42s}.sc-cut-s3{animation-delay:.84s}.sc-cut-s4{animation-delay:1.26s}
    @keyframes sc-cut-slice{0%{opacity:0;transform:translate(0,0)}10%{opacity:1}100%{opacity:1;transform:translate(46px,10px) rotate(25deg)}}</style>
    <rect x="30" y="96" width="290" height="70" rx="18" fill="#f3dcb4" stroke="${O}" stroke-width="3.5"/>
    <circle cx="300" cy="118" r="7" fill="#e9cfa0" stroke="${O}" stroke-width="3"/>
    <g class="sc-cut-carrot"><path d="M60 122 Q150 104 230 116 L230 142 Q150 152 60 140 Z" fill="#f28a3c" stroke="${O}" stroke-width="3.5"/>
      <path d="M60 124 l-18 -14 M60 132 l-22 -2 M60 138 l-16 12" stroke="#4f8a4f" stroke-width="5" stroke-linecap="round"/>
      <path d="M110 118 l6 6 M150 116 l6 6 M190 116 l6 6" stroke="#d26a22" stroke-width="3" stroke-linecap="round"/></g>
    ${[1, 2, 3, 4].map((i) => `<g class="sc-cut-sl sc-cut-s${i}"><ellipse cx="246" cy="130" rx="9" ry="14" fill="#f6a35a" stroke="${O}" stroke-width="3"/><circle cx="246" cy="130" r="4" fill="#f9c07d"/></g>`).join("")}
    <g class="sc-cut-knife"><path d="M236 8 L262 8 L262 118 Q249 132 236 120 Z" fill="#e9eef3" stroke="${O}" stroke-width="3.5"/>
      <rect x="232" y="-46" width="34" height="58" rx="10" fill="#e7787a" stroke="${O}" stroke-width="3.5"/>
      <path d="M244 30 l0 60" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".8"/></g></svg>`,

  crack: `<svg viewBox="0 0 340 190" aria-hidden="true"><style>
    .sc-cr-L{transform-origin:170px 60px;animation:sc-cr-L 1.8s ease-in-out infinite}.sc-cr-R{transform-origin:170px 60px;animation:sc-cr-R 1.8s ease-in-out infinite}
    @keyframes sc-cr-L{0%,30%{transform:none}55%,100%{transform:translate(-30px,-6px) rotate(-28deg)}}
    @keyframes sc-cr-R{0%,30%{transform:none}55%,100%{transform:translate(30px,-6px) rotate(28deg)}}
    .sc-cr-yolk{opacity:0;animation:sc-cr-drop 1.8s ease-in infinite}@keyframes sc-cr-drop{0%,45%{opacity:0;transform:translateY(0)}50%{opacity:1}80%,100%{opacity:1;transform:translateY(70px)}}
    .sc-cr-spl{opacity:0;transform-origin:170px 122px;animation:sc-cr-spl 1.8s infinite}@keyframes sc-cr-spl{0%,78%{opacity:0;transform:scale(.4)}85%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(1.3)}}
    .sc-cr-line{animation:sc-cr-line 1.8s infinite}@keyframes sc-cr-line{0%,20%{opacity:0}25%,40%{opacity:1}45%,100%{opacity:0}}</style>
    <path d="M70 120 Q170 210 270 120 Z" fill="#8fc694" stroke="${O}" stroke-width="3.5"/><ellipse cx="170" cy="120" rx="100" ry="18" fill="#cfe9cf" stroke="${O}" stroke-width="3.5"/>
    <g class="sc-cr-spl"><path d="M140 118 l-12 -10 M200 118 l12 -10 M170 112 l0 -14" stroke="#f6d54a" stroke-width="5" stroke-linecap="round"/></g>
    <g class="sc-cr-yolk"><ellipse cx="170" cy="66" rx="16" ry="12" fill="#ffd23f" stroke="${O}" stroke-width="3"/><ellipse cx="166" cy="62" rx="5" ry="3" fill="#fff6c2"/></g>
    <g class="sc-cr-L"><path d="M170 18 Q130 22 132 62 L148 56 L158 66 L170 58 Z" fill="#fff8ec" stroke="${O}" stroke-width="3.5" stroke-linejoin="round"/></g>
    <g class="sc-cr-R"><path d="M170 18 Q210 22 208 62 L196 56 L184 66 L170 58 Z" fill="#fff8ec" stroke="${O}" stroke-width="3.5" stroke-linejoin="round"/></g>
    <path class="sc-cr-line" d="M150 44 l8 6 l6 -6 l8 6" stroke="${O}" stroke-width="3" fill="none"/></svg>`,

  fry: `<svg viewBox="0 0 340 190" aria-hidden="true"><style>
    .sc-fr-pan{animation:sc-fr-jig .5s ease-in-out infinite}@keyframes sc-fr-jig{50%{transform:translateX(3px)}}
    .sc-fr-p{animation:sc-fr-pop 1s ease-out infinite}.sc-fr-p2{animation-delay:.33s}.sc-fr-p3{animation-delay:.66s}
    @keyframes sc-fr-pop{0%{transform:translateY(0)}35%{transform:translateY(-22px) rotate(30deg)}70%,100%{transform:translateY(0)}}
    .sc-fr-b{opacity:0;animation:sc-fr-bub .9s infinite}.sc-fr-b2{animation-delay:.3s}.sc-fr-b3{animation-delay:.6s}
    @keyframes sc-fr-bub{0%{opacity:0;transform:scale(.3)}40%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(1.4)}}
    .sc-fr-sz{animation:sc-fr-sz .35s steps(2) infinite}@keyframes sc-fr-sz{50%{opacity:.2}}
    .sc-fr-fl{transform-origin:170px 182px;animation:sc-fr-fl .3s ease-in-out infinite alternate}@keyframes sc-fr-fl{to{transform:scaleY(.8)}}</style>
    <g class="sc-fr-fl"><path d="M120 184 q10 -26 20 0 M160 184 q10 -32 20 0 M200 184 q10 -26 20 0" fill="#ffb34a" stroke="#f2794a" stroke-width="4"/></g>
    <g class="sc-fr-pan"><path d="M60 120 L280 120 Q270 166 170 166 Q70 166 60 120 Z" fill="#5b8fd6" stroke="${O}" stroke-width="3.5"/>
      <rect x="276" y="114" width="64" height="14" rx="7" fill="#6b4a3a" stroke="${O}" stroke-width="3.5"/>
      <ellipse cx="170" cy="120" rx="110" ry="14" fill="#f2d879" stroke="${O}" stroke-width="3.5"/>
      <g class="sc-fr-b"><circle cx="110" cy="118" r="6" fill="none" stroke="#fff" stroke-width="2.5"/></g><g class="sc-fr-b sc-fr-b2"><circle cx="220" cy="120" r="5" fill="none" stroke="#fff" stroke-width="2.5"/></g><g class="sc-fr-b sc-fr-b3"><circle cx="170" cy="124" r="4" fill="none" stroke="#fff" stroke-width="2.5"/></g>
      ${[[125, "sc-fr-p"], [165, "sc-fr-p sc-fr-p2"], [205, "sc-fr-p sc-fr-p3"]].map(([x, c]) => `<g class="${c}" style="transform-origin:${x}px 112px"><path d="M${x - 14} 114 q14 -16 28 0 q-14 8 -28 0z" fill="#f6efe0" stroke="${O}" stroke-width="3"/></g>`).join("")}</g>
    <g class="sc-fr-sz" stroke="${O}" stroke-width="3" stroke-linecap="round" fill="none"><path d="M96 80 q6 -8 0 -16 q-6 -8 0 -16"/><path d="M246 80 q6 -8 0 -16 q-6 -8 0 -16"/></g>
    <text class="sc-fr-sz" x="228" y="40" font-family="Bricolage Grotesque, sans-serif" font-weight="800" font-size="20" fill="#c25b2b">jiiii!</text></svg>`,

  stir: `<svg viewBox="0 0 340 190" aria-hidden="true"><style>
    .sc-st-spoon{transform-origin:170px 108px;animation:sc-st-circ 1.4s linear infinite}@keyframes sc-st-circ{to{transform:rotate(360deg)}}
    .sc-st-sw{transform-origin:170px 108px;animation:sc-st-circ 2.8s linear infinite reverse}</style>
    <ellipse cx="170" cy="108" rx="122" ry="70" fill="#f2c7cf" stroke="${O}" stroke-width="3.5"/>
    <ellipse cx="170" cy="108" rx="100" ry="54" fill="#e8553f" stroke="${O}" stroke-width="3"/>
    <g class="sc-st-sw" fill="none" stroke="#ff8f70" stroke-width="5" stroke-linecap="round"><path d="M120 108 a50 26 0 0 1 100 0"/><path d="M140 118 a30 14 0 0 0 60 0"/></g>
    <circle cx="132" cy="96" r="6" fill="#4f8a4f"/><circle cx="206" cy="120" r="5" fill="#4f8a4f"/><circle cx="190" cy="88" r="4" fill="#f6d54a"/>
    <g class="sc-st-spoon"><g transform="translate(222 92)"><ellipse rx="16" ry="10" fill="#d9a66e" stroke="${O}" stroke-width="3.5"/><rect x="-5" y="-92" width="10" height="86" rx="5" fill="#d9a66e" stroke="${O}" stroke-width="3.5"/></g></g></svg>`,

  simmer: `<svg viewBox="0 0 340 190" aria-hidden="true"><style>
    .sc-si-lid{transform-origin:150px 80px;animation:sc-si-lid .5s ease-in-out infinite}@keyframes sc-si-lid{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-5px) rotate(-2deg)}}
    .sc-si-st{opacity:0;animation:sc-si-steam 2.4s ease-out infinite}.sc-si-st2{animation-delay:.8s}.sc-si-st3{animation-delay:1.6s}
    @keyframes sc-si-steam{0%{opacity:0;transform:translateY(10px)}30%{opacity:.9}100%{opacity:0;transform:translateY(-40px)}}
    .sc-si-fl{transform-origin:150px 182px;animation:sc-si-fl .4s ease-in-out infinite alternate}@keyframes sc-si-fl{to{transform:scaleY(.75)}}</style>
    <g class="sc-si-fl"><path d="M110 184 q8 -18 16 0 M142 184 q8 -22 16 0 M174 184 q8 -18 16 0" fill="#7fb6ff" stroke="#4b7fd6" stroke-width="3.5"/></g>
    <path d="M70 84 L230 84 L222 164 Q150 176 78 164 Z" fill="#c9d3dc" stroke="${O}" stroke-width="3.5"/>
    <rect x="50" y="94" width="26" height="12" rx="6" fill="#6b4a3a" stroke="${O}" stroke-width="3"/><rect x="224" y="94" width="26" height="12" rx="6" fill="#6b4a3a" stroke="${O}" stroke-width="3"/>
    <g class="sc-si-lid"><path d="M64 84 Q150 50 236 84 Z" fill="#dfe6ec" stroke="${O}" stroke-width="3.5"/><circle cx="150" cy="62" r="8" fill="#6b4a3a" stroke="${O}" stroke-width="3"/></g>
    ${[[110, "sc-si-st"], [150, "sc-si-st sc-si-st2"], [190, "sc-si-st sc-si-st3"]].map(([x, c]) => `<path class="${c}" d="M${x} 46 q-10 -12 0 -24 q10 -12 0 -24" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/>`).join("")}</svg>`,
};
