const express  = require('express');
const Anthropic = require('@anthropic-ai/sdk');
const path      = require('path');

const app = express();
app.use(express.json({ limit: '10mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// Errors worth retrying — transient network / SSL blips
function isRetryable(err) {
  const msg = (err.message || '').toLowerCase();
  const code = (err.code || '').toLowerCase();
  const retryable = (
    msg.includes('ssl') ||
    msg.includes('econnreset') ||
    msg.includes('econnrefused') ||
    msg.includes('etimedout') ||
    msg.includes('socket hang up') ||
    msg.includes('bad record mac') ||
    code.includes('econnreset') ||
    code.includes('ssl')
  );
  if (retryable) console.log('[Then] Error is retryable:', msg.slice(0, 80));
  return retryable;
}

function delay(ms) {
  return new Promise(r => setTimeout(r, ms));
}

app.post('/api/chat', async (req, res) => {
  const { messages, system } = req.body;
  const apiKey = req.headers['x-api-key'];

  if (!apiKey) {
    return res.status(401).json({ error: 'API key required. Add it in Settings.' });
  }
  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'No messages provided.' });
  }

  const client = new Anthropic({ apiKey });

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  const MAX_RETRIES = 3;
  let attempt    = 0;
  let textWritten = false;

  function tryStream() {
    try {
      const stream = client.messages.stream({
        model:      'claude-opus-4-6',
        max_tokens: 1024,
        system:     system,
        messages:   messages,
      });

      let streamEnded = false;

      stream.on('text', (text) => {
        textWritten = true;
        res.write(`data: ${JSON.stringify({ text })}\n\n`);
      });

      stream.on('finalMessage', () => {
        if (!streamEnded) {
          streamEnded = true;
          res.write('data: [DONE]\n\n');
          res.end();
        }
      });

      stream.on('error', async (err) => {
        if (!streamEnded) {
          streamEnded = true;
          try { stream.abort?.(); } catch(e) {}
          handleStreamError(err);
        }
      });

      // Safety timeout — if no data for 30 seconds, kill it
      const timeout = setTimeout(() => {
        if (!streamEnded && !res.writableEnded) {
          streamEnded = true;
          try { stream.abort?.(); } catch(e) {}
          if (!res.writableEnded) {
            res.write(`data: ${JSON.stringify({ error: 'Request timeout' })}\n\n`);
            res.end();
          }
        }
      }, 30000);

      res.on('finish', () => { clearTimeout(timeout); });
      res.on('close', () => { clearTimeout(timeout); });
    } catch (err) {
      handleStreamError(err);
    }
  }

  async function handleStreamError(err) {
    // Only retry if no text was written yet (safe to restart)
    // and it's a transient SSL / network error
    if (!textWritten && isRetryable(err) && attempt < MAX_RETRIES) {
      attempt++;
      const backoff = 400 * Math.pow(2, attempt - 1); // 400ms, 800ms, 1600ms
      console.warn(`[Then] SSL/network error, retrying (${attempt}/${MAX_RETRIES}) in ${backoff}ms — ${err.message}`);
      await delay(backoff);
      if (!res.writableEnded) tryStream();
      return;
    }

    // Retries exhausted or text already flowing — surface the error
    if (!res.writableEnded) {
      res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
      res.end();
    }
  }

  tryStream();
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Then is running → http://localhost:${PORT}`);
});
