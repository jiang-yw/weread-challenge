"use strict";
// Run inside the existing project image; uses its installed Chromium/WebDriver.
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const {Builder, By, until, logging} = require("/usr/local/lib/node_modules/weread-selenium-cli/node_modules/selenium-webdriver");
const chrome = require("/usr/local/lib/node_modules/weread-selenium-cli/node_modules/selenium-webdriver/chrome");

(async () => {
  const outputDir = process.env.WEREAD_QA_DIR;
  assert.ok(outputDir, "Set WEREAD_QA_DIR to a scratch directory");
  await fs.mkdir(outputDir, {recursive: true});
  const options = new chrome.Options().setChromeBinaryPath("/usr/bin/chromium").addArguments(
    "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-software-rasterizer", "--disable-background-networking", "--no-first-run",
    `--user-data-dir=${process.env.XDG_CONFIG_HOME}/chromium-profile`
  );
  const driver = await new Builder().forBrowser("chrome").setChromeOptions(options)
    .setChromeService(new chrome.ServiceBuilder("/usr/bin/chromedriver")).build();
  const get = id => driver.findElement(By.id(id));
  const waitText = async (id, text) => driver.wait(async () => (await get(id).getText()).includes(text), 7000);
  const theme = () => driver.executeScript("return document.documentElement.dataset.theme");
  const fill = async (id, value) => { const field = await get(id); await field.clear(); await field.sendKeys(value); };
  const save = async () => {
    await get("notification-save").click();
    await waitText("notification-result", "配置已保存");
  };
  try {
    await driver.manage().window().setRect({width: 1440, height: 1450});
    await driver.get("http://127.0.0.1:7860/login");
    assert.equal(await theme(), "light");
    await driver.findElement(By.css("[data-theme-toggle]")).click();
    await driver.navigate().refresh();
    assert.equal(await theme(), "dark");
    await fill("password", "browser-test");
    await driver.findElement(By.css("button[type=submit]")).click();
    await waitText("connection", "服务已连接");
    assert.equal(await theme(), "dark");
    await driver.findElement(By.css("[data-theme-toggle]")).click();
    assert.equal(await theme(), "light");
    assert.match(await get("settings-primary").getText(), /每次阅读时长/);
    assert.match(await get("settings-primary").getText(), /68 分钟/);
    assert.equal(await driver.executeScript("return document.querySelector('.advanced').open"), false);
    assert.equal((await get("qr-block").findElements(By.css("img"))).length, 0);
    await waitText("notification-summary", "尚未配置通知");
    assert.equal(await get("notification-manager").isDisplayed(), false);

    await get("manage-notifications").click();
    await driver.wait(until.elementIsEnabled(get("notification-save")), 7000);
    await fill("webhook_url", "https://example.test/hook/test-token");
    await get("channel-enabled").click();
    await save();
    await waitText("notification-summary", "飞书");
    assert.equal(await get("webhook_url").getAttribute("value"), "***set***");
    await get("notification-test").click();
    await waitText("notification-result", "飞书测试通知已发送");
    await get("channel-enabled").click(); await save();
    await waitText("notification-summary", "已停用");

    await get("tab-bark").click();
    await fill("bark_key", "test-device-token");
    await get("channel-enabled").click(); await save();
    await get("notification-test").click(); await waitText("notification-result", "Bark 测试通知已发送");
    await get("tab-email").click();
    await fill("email_smtp", "smtp.example.test"); await fill("email_user", "sender@example.test");
    await fill("email_pass", "test-app-password"); await fill("email_to", "reader@example.test");
    await get("channel-enabled").click(); await save();
    await get("notification-test").click(); await waitText("notification-result", "测试邮件已提交");
    await get("manage-notifications").click();

    await get("log-level").findElement(By.css("option[value=error]")).click();
    await waitText("logs", "通知请求失败");
    assert.equal((await get("logs").getText()).includes("第 1 分钟"), false);
    await fill("log-search", "不存在的事件"); await waitText("logs", "暂无符合条件");
    await get("log-search").clear();
    await driver.executeScript("document.getElementById('log-search').dispatchEvent(new Event('input'))");
    await get("log-level").findElement(By.css("option[value=all]")).click();
    await waitText("logs", "本次阅读已完成");
    assert.equal((await get("logs").getText()).includes("Pressed down"), false);
    await get("log-follow").click();
    await driver.executeScript("document.getElementById('logs').scrollTop=0; return loadLogs()");
    assert.equal(await driver.executeScript("return document.getElementById('logs').scrollTop"), 0);

    await driver.executeScript("document.getElementById('restart-dialog').returnValue='confirm'");
    await get("restart-btn").click();
    assert.equal(await driver.executeScript("return document.getElementById('restart-dialog').returnValue"), "");
    assert.equal(await get("restart-dialog").getAttribute("open"), "true");
    await driver.findElement(By.css("#restart-dialog button[value=cancel]")).click();
    await driver.findElement(By.css(".advanced summary")).click();
    assert.match(await get("settings-advanced").getText(), /WEREAD_BROWSER/);
    await driver.findElement(By.css(".advanced summary")).click();

    await driver.executeScript("window.scrollTo(0,0)");
    await fs.writeFile(`${outputDir}/dashboard-light.png`, await driver.takeScreenshot(), "base64");
    await driver.findElement(By.css("[data-theme-toggle]")).click();
    await fs.writeFile(`${outputDir}/dashboard-dark.png`, await driver.takeScreenshot(), "base64");
    await driver.manage().window().setRect({width: 390, height: 900});
    await driver.findElement(By.css("[data-theme-toggle]")).click();
    assert.equal(await driver.executeScript("return document.documentElement.scrollWidth <= window.innerWidth"), true);
    await fs.writeFile(`${outputDir}/dashboard-mobile.png`, await driver.takeScreenshot(), "base64");
    const errors = (await driver.manage().logs().get(logging.Type.BROWSER)).filter(entry => entry.level.name === "SEVERE");
    assert.equal(errors.length, 0, JSON.stringify(errors));
    console.log("Browser smoke passed: theme, persistence, three notification channels, save/test, logs, stale QR, mobile layout.");
  } finally { await driver.quit(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
