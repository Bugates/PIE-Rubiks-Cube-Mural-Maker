(function(){
  const mount = document.getElementById("cubeMount");
  if (!mount) return;

  const heading = document.querySelector(".pageHeading");
  const letter = (document.body.dataset.letter || "O").toUpperCase();

  const COLORS = {
    blue:"#0051ba",
    red:"#c41e3a",
    orange:"#ff5800",
    yellow:"#ffd500",
    green:"#009e60",
    white:"#ffffff"
  };

  const LETTERS = {
    O:[
      1,1,1,1,1,
      1,0,0,0,1,
      1,0,0,0,1,
      1,0,0,0,1,
      1,1,1,1,1
    ],
    M:[
      1,0,0,0,1,
      1,1,0,1,1,
      1,0,1,0,1,
      1,0,0,0,1,
      1,0,0,0,1
    ],
    E:[
      1,1,1,1,1,
      1,0,0,0,0,
      1,1,1,1,0,
      1,0,0,0,0,
      1,1,1,1,1
    ],
    S:[
      1,1,1,1,1,
      1,0,0,0,0,
      1,1,1,1,1,
      0,0,0,0,1,
      1,1,1,1,1
    ],
    F:[
      1,1,1,1,1,
      1,0,0,0,0,
      1,1,1,1,0,
      1,0,0,0,0,
      1,0,0,0,0
    ],
    B:[
      1,1,1,1,0,
      1,0,0,0,1,
      1,1,1,1,0,
      1,0,0,0,1,
      1,1,1,1,0
    ],
    P:[
      1,1,1,1,0,
      1,0,0,0,1,
      1,1,1,1,0,
      1,0,0,0,0,
      1,0,0,0,0
    ],
    T:[
    1,1,1,1,1,
    0,0,1,0,0,
    0,0,1,0,0,
    0,0,1,0,0,
    0,0,1,0,0
    ],
    D:[
    1,1,1,1,0,
    1,0,0,0,1,
    1,0,0,0,1,
    1,0,0,0,1,
    1,1,1,1,0
    ]
  };

  function buildFace(color, pattern){
    const f = document.createElement("div");
    f.className = "face";
    for(let i=0;i<25;i++){
      const s = document.createElement("div");
      s.className = "sticker";
      if(pattern){
        s.style.background = pattern[i]
          ? COLORS.blue
          : COLORS.white;
      }else{
        s.style.background = color;
      }
      f.appendChild(s);
    }
    return f;
  }

  const cube = document.createElement("div");
  cube.className = "cube";

  const front = buildFace(COLORS.white, LETTERS[letter] || LETTERS.O);
  front.classList.add("front");

  const back   = buildFace(COLORS.green);  back.classList.add("back");
  const right  = buildFace(COLORS.red);    right.classList.add("right");
  const left   = buildFace(COLORS.orange); left.classList.add("left");
  const top    = buildFace(COLORS.yellow); top.classList.add("top");
  const bottom = buildFace(COLORS.blue);   bottom.classList.add("bottom");

  cube.append(front, back, right, left, top, bottom);

  const wrap = document.createElement("div");
  wrap.className = "cubeWrap";
  wrap.appendChild(cube);
  mount.appendChild(wrap);

  requestAnimationFrame(()=>{
    cube.classList.add("spin");
  });

  cube.addEventListener("animationend", ()=>{
    if (heading) heading.classList.add("text-reveal");
  }, { once:true });

})();
