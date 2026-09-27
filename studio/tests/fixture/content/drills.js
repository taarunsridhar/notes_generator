// Drill generators: window.DRILLS.<name> = function(box, U){ ... } (U.md, U.tex available). New numbers every time, nothing stored.
window.DRILLS.pv = function(box, U){
  function gen(){
    var C = 100 * (5 + Math.floor(Math.random() * 20)), r = (4 + Math.floor(Math.random() * 9)) / 100, t = 1 + Math.floor(Math.random() * 6), pv = C / Math.pow(1 + r, t);
    box.innerHTML = '<p>PV of ₹' + C + ' in ' + t + ' years at ' + Math.round(r * 100) + '%?</p><input class="pvin" inputmode="decimal" style="font:inherit;padding:6px"> <button class="btn ghost pvc">check</button> <button class="btn ghost pvn">new numbers</button><p class="pvo"></p>';
    box.querySelector('.pvc').onclick = function(){ var u = parseFloat(box.querySelector('.pvin').value); box.querySelector('.pvo').innerHTML = Math.abs(u - pv) < 0.5 ? '✓ right: ₹' + pv.toFixed(2) : '✗ ₹' + pv.toFixed(2) + ' = ' + C + ' / ' + (1 + r).toFixed(2) + '^' + t; };
    box.querySelector('.pvn').onclick = gen;
  }
  gen();
};
