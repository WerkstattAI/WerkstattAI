document.addEventListener('click', event => {
  const answer = event.target.closest('[data-frage-beantworten]');
  if (!answer) return;
  const purpose = document.querySelector('[data-message-purpose]');
  const form = purpose?.closest('form');
  const target = form?.querySelector('[data-reply-target]');
  if (!purpose || !target || ![...target.options].some(option => option.value === answer.dataset.frageBeantworten)) return;
  purpose.value = 'workshop_answer';
  purpose.dispatchEvent(new Event('change', {bubbles:true}));
  target.value = answer.dataset.frageBeantworten;
  target.dispatchEvent(new Event('change', {bubbles:true}));
  const options = form.querySelector('.nachrichtenoptionen');
  if (options) options.open = true;
  form.querySelector('textarea')?.focus();
});

// Nachladende Bilder halten das Ende nur fest, solange dort gelesen wird.
const verlauf = document.getElementById('messageThread');
const verlaufNavigation = document.querySelector('.verlauf-navigation');
const neuesteNachricht = document.querySelector('.neueste-nachricht');
if (verlauf && verlaufNavigation && neuesteNachricht) {
  let amEnde = true;
  const aktualisieren = () => {
    amEnde = verlauf.scrollHeight - verlauf.clientHeight - verlauf.scrollTop < 60;
    verlaufNavigation.hidden = amEnde;
  };
  const zumEnde = () => {
    verlauf.scrollTop = verlauf.scrollHeight;
    aktualisieren();
  };
  verlauf.addEventListener('scroll', aktualisieren, {passive:true});
  neuesteNachricht.addEventListener('click', () => {
    zumEnde();
    verlauf.focus({preventScroll:true});
  });
  verlauf.querySelectorAll('img').forEach(bild => {
    const nachgeladen = () => { if (amEnde) zumEnde(); else aktualisieren(); };
    bild.addEventListener('load', nachgeladen);
    bild.addEventListener('error', nachgeladen);
  });
  zumEnde();
}
