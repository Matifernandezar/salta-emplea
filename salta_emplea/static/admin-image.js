// Mejora progresiva: el servidor conserva permisos, cupo y revisión editorial.
(() => {
  const image = document.querySelector('.image-first input[name="image"]');
  if (!image) return;
  const form = image.form;
  const consent = form.querySelector('[name="allow_ocr"]');
  const status = document.getElementById('image-extraction-status');
  const button = form.querySelector('button[type="submit"]');
  let sending = false;
  function extract() {
    if (sending || !image.files.length || !consent?.checked) return;
    if (image.files[0].size > 4 * 1024 * 1024) {
      status.textContent = 'La imagen supera 4 MB. Elegí una versión más pequeña.';
      return;
    }
    // La lectura debe poder empezar con Puesto y el resto del formulario vacíos.
    // El servidor valida los datos y completa únicamente los campos vacíos.
    sending = true;
    status.textContent = 'Leyendo la imagen y completando el borrador… Esperá un momento.';
    form.setAttribute('aria-busy', 'true');
    button.textContent = 'Completando datos…';
    button.formNoValidate = true;
    form.requestSubmit(button);
  }
  image.addEventListener('change', extract);
  consent?.addEventListener('change', extract);
  form.addEventListener('submit', () => {
    // No deshabilitar el archivo ni el permiso: deben enviarse al servidor.
    button.disabled = true;
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) {
      sending = false;
      button.disabled = false;
      button.formNoValidate = false;
      button.textContent = 'Guardar para revisión';
      form.removeAttribute('aria-busy');
      status.textContent = 'Elegí una imagen para preparar el borrador.';
    }
  });
})();
