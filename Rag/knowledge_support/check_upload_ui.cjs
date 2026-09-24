const { chromium } = require('C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: 'C:/Users/Lenovo/AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
    await page.goto('http://127.0.0.1:8501');
    await page.getByText('上传文档', {exact: true}).click();
    await page.getByText('上传知识文档', {exact: true}).waitFor();
    await page.locator('input[type=file]').setInputFiles({name: '演示知识.txt', mimeType: 'text/plain', buffer: Buffer.from('这是一份用于测试上传界面的演示文档。\n\n客服工作时间为周一至周五。\n\n此内容仅用于本地预览，没有导入知识库。')});
    await page.getByRole('button', {name: '导入知识库', exact: true}).waitFor();
    await page.getByText('片段 1', {exact: true}).waitFor();
    if (await page.locator('[data-testid=stException]').count()) throw new Error('Streamlit exception');
    fs.mkdirSync('output/playwright', {recursive: true});
    await page.screenshot({path: 'output/playwright/upload-preview.png', fullPage: true});
    console.log('PASS: upload navigation, synthetic TXT upload, local preview, import button; no import submitted');
  } finally { await browser.close(); }
})();
