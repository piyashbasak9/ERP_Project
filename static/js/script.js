// Placeholder JS
console.log('Placeholder script loaded');

document.addEventListener('DOMContentLoaded', function () {
	// Auto-close Bootstrap alerts after 5 seconds
	const alerts = document.querySelectorAll('.alert');
	alerts.forEach(function (el) {
		setTimeout(function () {
			try {
				const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
				bsAlert.close();
			} catch (e) {
				// fallback: remove element
				el.classList.remove('show');
				el.remove();
			}
		}, 5000);
	});
});
