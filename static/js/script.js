console.log('Placeholder script loaded');

document.addEventListener('DOMContentLoaded', function () {
	const alerts = document.querySelectorAll('.alert');
	alerts.forEach(function (el) {
		setTimeout(function () {
			try {
				const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
				bsAlert.close();
			} catch (e) {
				el.classList.remove('show');
				el.remove();
			}
		}, 5000);
	});
});
