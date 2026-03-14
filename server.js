const express = require('express');
const { chromium } = require('playwright');
const { execSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const app = express();
app.use(express.json({ limit: '20mb' }));

// CORS — allow VI Studio to call this from any origin
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();
  next();
});

// Health check
app.get('/', (req, res) => {
  res.json({ status: 'ok', service: 'vi-render' });
});

// Render video
app.post('/render', async (req, res) => {
  const { html, duration = 15, filename = 'vi-template' } = req.body;
  if (!html) return res.status(400).json({ error: 'html is required' });

  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'vi-render-'));
  const htmlFile = path.join(tmpDir, 'template.html');
  const mp4File = path.join(tmpDir, 'output.mp4');

  let browser;
  try {
    fs.writeFileSync(htmlFile, html, 'utf8');

    console.log(`[render] Starting: ${duration}s, ${filename}`);

    browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--force-device-scale-factor=1',
        '--js-flags=--max-old-space-size=256',
      ]
    });

    // Record at 960×540 to stay within 512MB free tier RAM
    // ffmpeg upscales to 1920×1080 during conversion
    const context = await browser.newContext({
      viewport: { width: 960, height: 540 },
      deviceScaleFactor: 1,
      recordVideo: {
        dir: tmpDir,
        size: { width: 960, height: 540 }
      }
    });

    const page = await context.newPage();

    // Load template
    await page.goto('file://' + htmlFile, {
      waitUntil: 'domcontentloaded',
      timeout: 10000
    }).catch(() => {});

    // Wait for fonts and images to settle
    await page.waitForTimeout(1500);

    // Reload to restart CSS animations from t=0
    await page.reload({ waitUntil: 'domcontentloaded' }).catch(() => {});
    await page.waitForTimeout(400);

    console.log(`[render] Recording ${duration}s...`);

    // Record for the full duration
    await page.waitForTimeout(duration * 1000);

    // Close context to flush video
    const video = await page.video();
    await context.close();
    await browser.close();
    browser = null;

    // Get the WebM file Playwright created
    const webmPath = await video.path();

    console.log(`[render] Converting to MP4...`);

    // Convert WebM → MP4, upscale 960×540 → 1920×1080
    execSync(
      `ffmpeg -y -i "${webmPath}" -vf scale=1920:1080:flags=lanczos -c:v libx264 -preset fast -crf 18 -movflags +faststart -pix_fmt yuv420p "${mp4File}"`,
      { timeout: 60000 }
    );

    const videoBuffer = fs.readFileSync(mp4File);
    const today = new Date().toISOString().slice(0, 10);

    console.log(`[render] Done: ${(videoBuffer.length / 1024 / 1024).toFixed(1)} MB`);

    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}-${today}.mp4"`);
    res.setHeader('Content-Length', videoBuffer.length);
    return res.status(200).send(videoBuffer);

  } catch (err) {
    console.error('[render] Error:', err.message);
    return res.status(500).json({ error: err.message });
  } finally {
    if (browser) try { await browser.close(); } catch {}
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`VI Render Service running on port ${PORT}`);
});
