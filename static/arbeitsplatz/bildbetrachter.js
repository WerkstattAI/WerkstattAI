(() => {
  // Nur bestehende, zugriffsgeschützte Medienlinks verwenden; keine öffentliche Kopie.
  const dialog = document.createElement('dialog');
  dialog.className = 'bildbetrachter';
  dialog.setAttribute('aria-label', 'Kundenfoto');
  dialog.innerHTML = '<header><h2>Kundenfoto</h2><button type="button" autofocus>Schließen</button></header><p role="status">Foto wird geladen …</p><img alt="Vergrößertes Kundenfoto" hidden><p><a target="_blank" rel="noopener noreferrer">Original öffnen / Fehlerdetails</a></p>';
  document.body.append(dialog);
  const picture = dialog.querySelector('img');
  const status = dialog.querySelector('[role=status]');
  let trigger;
  dialog.querySelector('button').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {picture.removeAttribute('src');trigger?.focus();});
  picture.addEventListener('load', () => {picture.hidden=false;status.hidden=true;});
  picture.addEventListener('error', () => {
    picture.hidden=true;status.hidden=false;
    status.textContent='Dieses Foto konnte nicht geladen werden. Der Original-Link zeigt die genaue Ursache. Bei nicht mehr verfügbaren WhatsApp-Fotos bitten Sie den Kunden um erneutes Senden.';
  });
  function fehler(img) {
    const card=img.closest('[data-kundenfoto]');
    if (card) {img.hidden=true;card.querySelector('.bild-fehler').hidden=false;}
  }
  document.addEventListener('error', event => {if(event.target.matches?.('[data-kundenfoto] img')) fehler(event.target);}, true);
  document.querySelectorAll('[data-kundenfoto] img').forEach(img => {if(img.complete && !img.naturalWidth) fehler(img);});
  document.addEventListener('click', event => {
    const link=event.target.closest('[data-bild-oeffnen]');
    if(!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url=new URL(link.href,location.href);
    if(url.origin !== location.origin || !url.pathname.startsWith('/dashboard/whatsapp/medien/')) return;
    event.preventDefault();trigger=link;
    picture.hidden=true;status.hidden=false;status.textContent='Foto wird geladen …';
    dialog.querySelector('a').href=url.href;
    dialog.showModal();picture.src=url.href;
  });
})();
