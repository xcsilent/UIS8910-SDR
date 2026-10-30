"""Small OFDM synchronizer/BER self-test for the real-time host path."""
import numpy as np

def qpsk(bits): return ((1-2*bits[0::2].astype(np.int8))+1j*(1-2*bits[1::2].astype(np.int8)))/np.sqrt(2)
def make(seed=1,n=96,fft=256,cp=32,frames=8):
 r=np.random.default_rng(seed);out=[];payload=[];bins=np.r_[np.arange(-n//2,0),np.arange(1,n//2+1)]
 for k in range(frames):
  b=r.integers(0,2,2*n,dtype=np.uint8);d=qpsk(b);x=np.zeros(fft,np.complex64);x[bins%fft]=d;u=np.fft.ifft(x);out.append(np.r_[u[-cp:],u]);payload.append(b)
 return np.concatenate(out),payload,bins
def demod(z,payload,bins,fft=256,cp=32):
 step=fft+cp;got=[]
 for i in range(len(payload)):
  u=z[i*step+cp:(i+1)*step]
  if len(u)<fft:break
  d=np.fft.fft(u)[bins%fft];b=np.empty(2*len(d),dtype=np.uint8);b[0::2]=(d.real<0);b[1::2]=(d.imag<0);got.append(b)
 n=sum(len(x) for x in got);err=sum(int(np.count_nonzero(a[:len(b)]!=b)) for a,b in zip(payload,got));return {'frames':len(got),'ber':err/n if n else None,'samples':len(z)}
def selftest():
 z,p,b=make();r=demod(z,p,b);assert r['frames']==8 and r['ber']==0,r;return r
if __name__=='__main__':print(selftest())
