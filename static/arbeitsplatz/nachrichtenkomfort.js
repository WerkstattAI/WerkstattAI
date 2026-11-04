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
