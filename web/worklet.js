// Native-rate microphone to 16 kHz mono PCM16, in bounded 160 ms messages.
class DownsampleProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions?.targetRate || 16000;
    this.ratio = sampleRate / this.targetRate;
    this.samples = []; this.position = 0; this.pcm = []; this.muted = false;
    this.port.onmessage = event => {
      if (event.data?.type === 'mute') {
        this.muted = !!event.data.value;
        this.samples = []; this.pcm = []; this.position = 0;
      }
    };
  }
  process(inputs) {
    if (this.muted || !inputs[0]?.[0]) return true;
    this.samples.push(...inputs[0][0]);
    while (this.position + 1 < this.samples.length) {
      const index = Math.floor(this.position), fraction = this.position - index;
      const value = this.samples[index] * (1 - fraction) + this.samples[index + 1] * fraction;
      this.pcm.push(Math.round(Math.max(-1, Math.min(1, value)) * 32767));
      this.position += this.ratio;
      if (this.pcm.length === 2560) {
        const frame = new Int16Array(this.pcm); this.pcm = [];
        this.port.postMessage(frame.buffer, [frame.buffer]);
      }
    }
    const consumed = Math.floor(this.position);
    this.samples = this.samples.slice(consumed); this.position -= consumed;
    return true;
  }
}
registerProcessor('pl-downsample', DownsampleProcessor);
