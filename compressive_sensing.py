import numpy as np
import scipy.fftpack as fft
from sklearn.linear_model import OrthogonalMatchingPursuit
import psutil
import time
import threading

class CompressiveSenser:
    def __init__(self, frame_size=256, ratio=4):
        """
        Initializes the Sub-Nyquist compressive sensor geometry constraint.
        y = Phi * x, where Phi is a highly sparse Gaussian Measurement Matrix.
        """
        self.N = frame_size
        self.ratio = ratio
        self.M = max(1, self.N // ratio)
        
        # Generation of reproducible Gaussian measurement constraint
        np.random.seed(42)  
        self.Phi = np.random.randn(self.M, self.N) / np.sqrt(self.M)
        
        # Basis dictionary Psi (Inverse Discrete Cosine Transform) for frequency sparsity
        self.Psi = fft.idct(np.eye(self.N), norm='ortho', axis=0)
        
        # Overall transformation Theta for L1 Minimization framework
        self.Theta = self.Phi @ self.Psi
        
        # Assuming typical IoT vibration signal sparsity level of 10-15% of frame bandwidth
        self.k = max(1, int(0.12 * self.N))
        self.omp = OrthogonalMatchingPursuit(n_nonzero_coefs=self.k)

    def compress(self, x: np.ndarray):
        """ Projects high-dimensional signal into subspace y (O(M)). Returns matrix of compressed frames. """
        # Force align to exact frames via zero-pad
        pad_len = (self.N - (len(x) % self.N)) % self.N
        if pad_len > 0:
            x = np.pad(x, (0, pad_len))
            
        frames = x.reshape(-1, self.N)
        y_frames = (self.Phi @ frames.T).T
        return y_frames, len(x) - pad_len

    def _reconstruct_core(self, y_frames, orig_len):
        """ Decodes measurements exclusively solving L1 constraint. Highly CPU intensive. """
        x_recon = np.zeros(len(y_frames) * self.N, dtype=np.float32)
        idx = 0
        for y in y_frames:
            self.omp.fit(self.Theta, y)
            s_hat = self.omp.coef_
            x_hat = self.Psi @ s_hat
            x_recon[idx:idx+self.N] = x_hat
            idx += self.N
        return x_recon[:orig_len]

    def reconstruct_eagerly(self, y_frames, orig_len):
        """ Phase 3.1: Synchronous reconstruction mapping. Returns original dimensionality. """
        return self._reconstruct_core(y_frames, orig_len)

    def reconstruct_on_idle(self, y_frames, orig_len, callback_fn):
        """ Phase 3.1: Async dispatch. Rebuilds only when host drops below 30% CPU load threshold. """
        def background_sweeper():
            while psutil.cpu_percent(interval=1) > 30.0:
                time.sleep(1) # Backoff if heavily contested
                
            x_recon = self._reconstruct_core(y_frames, orig_len)
            callback_fn(x_recon)
            
        # Spawn headless agent
        t = threading.Thread(target=background_sweeper, daemon=True)
        t.start()
        return t

    def reconstruct_on_query(self, y_frames, orig_len):
        """ Phase 3.1: Lazily bypasses up-front CPU expense and decodes exactly on datalake extraction. """
        return self._reconstruct_core(y_frames, orig_len)

def evaluate_quality(x_orig, x_recon):
    """ Evaluates distortion boundaries via MSE and SNR (dB). """
    mse = np.mean((x_orig - x_recon)**2)
    signal_power = np.mean(x_orig**2)
    snr_db = 10 * np.log10(signal_power / mse) if mse > 0 else float('inf')
    return mse, snr_db
