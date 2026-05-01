// ===== NAV SCROLL BEHAVIOR =====
const nav = document.querySelector('.nav');
function updateNav() {
  if (window.scrollY > 40) {
    nav?.classList.add('scrolled');
    nav?.classList.remove('nav-transparent');
  } else {
    nav?.classList.remove('scrolled');
    if (nav?.dataset.transparent === 'true') nav.classList.add('nav-transparent');
  }
}
window.addEventListener('scroll', updateNav, { passive: true });
updateNav();

// ===== ACTIVE NAV LINK =====
document.querySelectorAll('.nav-links a').forEach(link => {
  if (link.href === location.href || location.pathname.includes(link.getAttribute('href')?.replace('.html',''))) {
    link.classList.add('active');
  }
});

// ===== MOBILE NAV =====
const hamburger = document.querySelector('.nav-hamburger');
const mobileNav = document.querySelector('.nav-mobile');
hamburger?.addEventListener('click', () => {
  const open = mobileNav.style.display === 'flex';
  mobileNav.style.display = open ? 'none' : 'flex';
});

// ===== SCROLL REVEAL =====
const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      e.target.classList.add('visible');
      observer.unobserve(e.target);
    }
  });
}, { threshold: 0.12 });
document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

// ===== ANIMATED COUNTERS =====
function animateCounter(el) {
  const target = parseInt(el.dataset.target);
  const suffix = el.dataset.suffix || '';
  const prefix = el.dataset.prefix || '';
  const duration = 1800;
  const start = performance.now();
  function update(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.round(eased * target);
    el.textContent = prefix + current.toLocaleString('fr-FR') + suffix;
    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}
const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      animateCounter(e.target);
      counterObserver.unobserve(e.target);
    }
  });
}, { threshold: 0.5 });
document.querySelectorAll('.counter').forEach(el => counterObserver.observe(el));

// ===== TABS =====
document.querySelectorAll('.tab-bar').forEach(bar => {
  bar.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const group = btn.dataset.group;
      const target = btn.dataset.target;
      bar.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll(`.tab-content[data-group="${group}"]`).forEach(c => {
        c.classList.toggle('active', c.dataset.tab === target);
      });
    });
  });
});

// ===== TOOTH HOVER ANIMATION =====
document.querySelectorAll('.odo-tooth').forEach(tooth => {
  tooth.addEventListener('mouseenter', function() {
    this.style.transform = 'scale(1.15) translateY(-3px)';
    this.style.transition = 'all 0.15s';
  });
  tooth.addEventListener('mouseleave', function() {
    this.style.transform = '';
  });
});

// ===== SMOOTH SCROLL =====
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const target = document.querySelector(a.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

// ===== CONTACT FORM =====
const contactForm = document.querySelector('#contact-form');
contactForm?.addEventListener('submit', e => {
  e.preventDefault();
  const btn = contactForm.querySelector('[type="submit"]');
  btn.textContent = 'Message envoyé ✓';
  btn.style.background = '#22c55e';
  btn.disabled = true;
  setTimeout(() => {
    btn.textContent = 'Envoyer la demande';
    btn.style.background = '';
    btn.disabled = false;
    contactForm.reset();
  }, 3000);
});
