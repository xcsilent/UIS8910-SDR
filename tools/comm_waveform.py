"""Generate repeatable QPSK/OFDM complex64 IQ files for UHD playback."""
import argparse,json,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from comm_protocol import stream, FRAME_SYMBOLS, SPS, VERSION as QPSK_VERSION, rrc
import comm_ofdm_realtime as framed_ofdm

def qpsk(nsym,seed=1,sps=8):
 p,_=stream(max(1,(nsym+FRAME_SYMBOLS-1)//FRAME_SYMBOLS),sps=sps)
 return (0.25*p).astype(np.complex64),dict(symbols=len(p)//sps,samples_per_symbol=sps,seed=seed,framing='fixed-preamble-sequence-prbs')
def ofdm(symbols=200,nfft=256,cp=32,active=96,seed=1):
 if (nfft,cp,active)!=(256,32,96):raise ValueError('framed OFDM v1 requires FFT256/CP32/active96')
 frames=max(1,(symbols+15)//16)
 return framed_ofdm.stream(frames),dict(protocol=framed_ofdm.VERSION,frames=frames,fft=nfft,cp=cp,active_subcarriers=active,seed=seed)
def main():
 a=argparse.ArgumentParser();a.add_argument('--modulation',choices=['qpsk','ofdm'],required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--seconds',type=float,default=2);a.add_argument('--sample-rate',type=int,default=1920000);a.add_argument('--amplitude-scale',type=float,default=1.);args=a.parse_args();n=max(1,int(args.seconds*args.sample_rate))
 if not np.isfinite(args.amplitude_scale) or args.amplitude_scale<=0:a.error('amplitude-scale must be finite and positive')
 args.output.parent.mkdir(parents=True,exist_ok=True)
 if args.modulation=='qpsk':
  if args.sample_rate not in (1920000,3840000):a.error('QPSK requires BW0/BW1 sample rate')
  frame_samples=FRAME_SYMBOLS*SPS
  frames=(n+frame_samples-1)//frame_samples
  remaining=n;peak=0.;tail=np.zeros(len(rrc())-1,np.complex64)
  with args.output.open('wb') as sink:
   for first in range(0,frames,128):
    count=min(128,frames-first)
    z,_=stream(count,first_seq=first)
    z[:len(tail)]+=tail
    tail=z[count*frame_samples:].copy()
    z=(.25*args.amplitude_scale*z[:min(count*frame_samples,remaining)]).astype(np.complex64)
    z.tofile(sink);remaining-=len(z);peak=max(peak,float(np.max(np.abs(z))))
  meta=dict(protocol=QPSK_VERSION,frames=frames,complete_frames=max(0,(n-len(tail))//frame_samples),first_sequence=0,frame_samples=frame_samples,samples_per_symbol=SPS,symbol_rate=args.sample_rate//SPS,rrc_rolloff=.25,sequence_repeats=False)
 else:
  if args.sample_rate not in (1920000,3840000):a.error('OFDM requires BW0/BW1 sample rate')
  frames=(n+framed_ofdm.FRAME_SAMPLES-1)//framed_ofdm.FRAME_SAMPLES
  remaining=n;peak=0.
  with args.output.open('wb') as sink:
   for first in range(0,frames,128):
    z=(args.amplitude_scale*framed_ofdm.stream(min(128,frames-first),first)[:remaining]).astype(np.complex64)
    z.tofile(sink);remaining-=len(z);peak=max(peak,float(np.max(np.abs(z))))
  meta=dict(protocol=framed_ofdm.VERSION,frames=frames,complete_frames=n//framed_ofdm.FRAME_SAMPLES,first_sequence=0,frame_samples=framed_ofdm.FRAME_SAMPLES,fft=256,cp=32,active_subcarriers=96,pilot_subcarriers=8,payload_bits_per_frame=framed_ofdm.PAYLOAD_BITS,subcarrier_spacing_hz=args.sample_rate/256,sequence_repeats=False)
 if peak>1.:
  args.output.with_suffix('.json').unlink(missing_ok=True)
  a.error('generated waveform exceeds digital full scale; reduce amplitude-scale')
 meta.update(modulation=args.modulation,sample_rate_hz=args.sample_rate,samples=n,amplitude=peak,amplitude_scale=args.amplitude_scale);args.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n');print(json.dumps(meta))
if __name__=='__main__':main()
