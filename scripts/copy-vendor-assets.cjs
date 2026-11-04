const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const mappings = [
    ["bootstrap/dist/css/bootstrap.min.css", "static/vendor/bootstrap/css/bootstrap.min.css"],
    ["bootstrap/dist/js/bootstrap.bundle.min.js", "static/vendor/bootstrap/js/bootstrap.bundle.min.js"],
    ["bootstrap-icons/font", "static/vendor/bootstrap-icons/font"],
    ["jquery/dist/jquery.min.js", "static/vendor/jquery/jquery.min.js"],
    ["jquery-ui-dist/jquery-ui.min.js", "static/vendor/jquery-ui/jquery-ui.min.js"],
    ["jquery-ui-dist/jquery-ui.min.css", "static/vendor/jquery-ui/jquery-ui.min.css"],
    ["jquery-ui-dist/images", "static/vendor/jquery-ui/images"],
    ["free-jqgrid/js/jquery.jqgrid.min.js", "static/vendor/free-jqgrid/js/jquery.jqgrid.min.js"],
    ["free-jqgrid/js/i18n/grid.locale-en.js", "static/vendor/free-jqgrid/js/i18n/grid.locale-en.js"],
    ["free-jqgrid/css", "static/vendor/free-jqgrid/css"],
    ["slim-select/dist/slimselect.min.js", "static/vendor/slim-select/slimselect.min.js"],
    ["slim-select/dist/slimselect.css", "static/vendor/slim-select/slimselect.css"],
];
const licenses = [
    ["bootstrap", "bootstrap"],
    ["bootstrap-icons", "bootstrap-icons"],
    ["free-jqgrid", "free-jqgrid"],
    ["jquery", "jquery"],
    ["jquery-ui-dist", "jquery-ui-dist"],
    ["slim-select", "slim-select"],
];

for (const [source, destination] of mappings) {
    const sourcePath = path.join(root, "node_modules", source);
    if (!fs.existsSync(sourcePath)) {
        throw new Error(`Missing frontend package asset: ${sourcePath}`);
    }
    const destinationPath = path.join(root, destination);
    fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
    fs.cpSync(sourcePath, destinationPath, { recursive: true });
}

for (const [packageName, licenseName] of licenses) {
    const packagePath = path.join(root, "node_modules", packageName);
    const licensePath = ["LICENSE", "LICENSE.md", "LICENSE.txt"]
        .map((name) => path.join(packagePath, name))
        .find(fs.existsSync);
    if (!licensePath) {
        throw new Error(`Missing license file for frontend package: ${packageName}`);
    }
    const destinationPath = path.join(root, "static/vendor/licenses", `${licenseName}.txt`);
    fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
    fs.copyFileSync(licensePath, destinationPath);
}
