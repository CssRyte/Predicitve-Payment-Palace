document.querySelectorAll('[data-open-drawer]').forEach(btn=>btn.addEventListener('click',()=>document.querySelector('#itemDrawer')?.classList.add('open')));
document.querySelectorAll('[data-close-drawer]').forEach(btn=>btn.addEventListener('click',()=>document.querySelector('#itemDrawer')?.classList.remove('open')));
document.querySelectorAll('[data-tab-target]').forEach(tab=>tab.addEventListener('click',()=> {
  const target=tab.dataset.tabTarget;
  if(target) location.href=target;
}
));
