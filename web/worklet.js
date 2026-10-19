// Patient Listener — mic AudioWorklet (live path only, workbook D-08).
// Captures at the hardware rate and downsamples to 16 kHz mono Int16 in the worklet, because
// Firefox rejects a 16 kHz mic AudioContext. The main thread opens the WebSocket and sends the
// Int16 frames as binary; the server runs VAD + ASR. In demo mode this file is never loaded.

class DownsampleProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = (options.processorOptions && options.processorOptions.targetRate) || 16000;
    this.inRate = sampleRate; // the context's actual rate
    this.ratio = this.inRate / this.targetRate;
    this._buf = [];
    this._muted = false;
    this.port.onmessage = (e) => {
      if (e.data && e.data.type === 'mute') this._muted = !!e.data.value; // half-duplex
    };
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0 || this._muted) return true;
    const ch = input[0];
    if (!ch) return true;

    // Simple decimation with linear interpolation to the target rate.
    for (let i = 0; i < ch.length; i++) this._buf.push(ch[i]);
    const out = [];
    let idx = 0;
    while (idx + this.ratio < this._buf.length) {
      const pos = idx;
      const low = Math.floor(pos);
      const frac = pos - low;
      const s = this._buf[low] * (1 - frac) + (this._buf[low + 1] || 0) * frac;
      out.push(Math.max(-1, Math.min(1, s)));
      idx += this.ratio;
    }
    this._buf = this._buf.slice(Math.floor(idx));

    if (out.length) {
      const pcm = new Int16Array(out.length);
      for (let i = 0; i < out.length; i++) pcm[i] = (out[i] * 0x7fff) | 0;
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor('pl-downsample', DownsampleProcessor);
