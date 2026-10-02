const fs = require("node:fs");
const path = require("node:path");
const sharp = require("../../frontend/node_modules/sharp");

const iconset = process.argv[2];
if (!iconset) throw new Error("Iconset destination is required");
fs.mkdirSync(iconset, { recursive: true });

const svg = fs.readFileSync(path.join(__dirname, "../../frontend/src/app/icon.svg"), "utf8");
const withBackground = svg.replace(
  /(<svg[^>]*>)/,
  '$1<rect width="240" height="240" rx="52" fill="#ECE6D6"/>',
);
const sizes = [16, 32, 128, 256, 512];

Promise.all(
  sizes.flatMap((size) => [
    sharp(Buffer.from(withBackground)).resize(size, size).png().toFile(path.join(iconset, `icon_${size}x${size}.png`)),
    sharp(Buffer.from(withBackground)).resize(size * 2, size * 2).png().toFile(path.join(iconset, `icon_${size}x${size}@2x.png`)),
  ]),
).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
