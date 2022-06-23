import numpy as np
from mpmath import gamma, hyper
from scipy.optimize import curve_fit
from .geom_coeffs import get_coeff
from ..utils.signal_processing import numdiff, smoothM

class TingModel:
    def __init__(self, ind_geom, tip_param, modelFt) -> None:
        # Tip geomtry params
        self.ind_geom = ind_geom         # No units
        self.tip_parameter = tip_param   # If radius units is meters, If half angle units is degrees
        self.modelFt = modelFt
        # Compiutation params
        self.fit_hline_flag = False
        self.apply_bec_flag = False
        self.bec_model = None
        # Model params #####################
        self.n_params = None
        # Contact point
        self.t0 = 0
        self.t0_init = 0
        self.t0_min = -np.inf
        self.t0_max = np.inf
        # Apparent Young's Modulus
        self.E0 = 1000
        self.E0_init = 1000
        self.E0_min = -np.inf
        self.E0_max = np.inf
        # Time of contact
        self.tc = 0
        self.tc_init = 0
        self.tc_min = -np.inf
        self.tc_max = np.inf
        # Fluidity exponent
        self.betaE = 0.2
        self.betaE_init = 0.2
        self.betaE_min = 0
        self.betaE_max = 1
        # Contact force
        self.F0 = 0
        self.F0_init = 0
        self.F0_min = -np.inf
        self.F0_max = np.inf
        # Poisson ratio
        self.poisson_ratio = 0.5
        # Viscous drag factor
        self.vdrag = 0

    def SolveAnalytical(self, ttc, trc, t1, model_probe, geom_coeff, v0t, v0r, v0, E0, betaE, t0, F0, vdrag):
        # TO DO: ADD REFERENCE!!!
        if model_probe == 'paraboloid':
            Cp=1/geom_coeff
            Ftp=3/2*v0t**(3/2)*E0*t0**betaE*np.sqrt(np.pi)*np.array(gamma(1-betaE), dtype=float)/(Cp*2*np.array(gamma(5/2-betaE), dtype=float))*ttc**(3/2-betaE)
            if np.abs(v0r-v0t)/v0t<0.01:
                Frp=3/2*v0r**(3/2)*E0*t0**betaE*np.sqrt(np.pi)*np.array(gamma(1-betaE), dtype=float)/(Cp*2*np.array(gamma(5/2-betaE), dtype=float))*t1**(3/2-betaE)
            else:
                # Downsample t1 and trc to speed up hypergeom:
                # start:stop:step
                downsamp_step = 3
                downsamp_t1 = t1[::downsamp_step]
                downsamp_trc = trc[::downsamp_step]
                A = [hyper([1, 1/2-betaE], [1/2], downsamp_t1[i]/downsamp_trc[i]) for i in range(len(downsamp_trc))]
                Frp=3/Cp*E0*v0t**(3/2)*t0**betaE/(3+4*(betaE-2)*betaE)*t1**(-1/2)*(trc-t1)**(1-betaE)*\
                    (-trc+(2*betaE-1)*t1+trc*np.array(A, dtype=float))
            return np.r_[Ftp+v0t*vdrag, Frp-v0r*vdrag]+F0
        elif model_probe in ('cone', 'pyramid'):
            Cc=1/geom_coeff
            if np.abs(v0r-v0t)/v0t<0.01:
                Ftc=2*v0**2*E0*t0**betaE/Cc/(2-3*betaE+betaE**2)*ttc**(2-betaE)
                Frc=-2*v0**2.*E0*t0**betaE/Cc/(2-3*betaE+betaE**2)*((trc-t1)**(1-betaE)*(trc+(1-betaE)*t1)-\
                    trc**(1-betaE)*(trc))
            else:
                Ftc=2*v0t**2*E0*t0**betaE/Cc/(2-3*betaE+betaE**2)*ttc**(2-betaE)
                Frc=-2*v0t**2*E0*t0**betaE/Cc/(2-3*betaE+betaE**2)*((trc-t1)**(1-betaE)*(trc+(1-betaE)*t1)-\
                    trc**(1-betaE)*(trc))
            return np.r_[Ftc+v0t*vdrag, Frc-v0r*vdrag]+F0
    
    def SolveNumerical(self, delta, time_, geom_coeff, geom_exp, v0t, v0r, E0, betaE, F0, vdrag, smooth_w, idx_tm, idxCt, idxCr):
        delta0 = delta - delta[idxCt[0]]
        delta_Uto_dot = np.zeros(len(delta0))
        A = smoothM(np.r_[numdiff(delta0[idxCt]**geom_exp), numdiff(delta0[idxCr[0]:]**geom_exp)], smooth_w)
        if len(A) < len(delta_Uto_dot[idxCt[0]:]):
            A = np.append(A, A[-1])
        delta_Uto_dot[idxCt[0]:] = A
        delta_dot = np.zeros(len(delta0))
        B = smoothM(np.r_[numdiff(delta0[idxCt]), numdiff(delta0[idxCr[0]:])], smooth_w)
        if len(B) < len(delta_Uto_dot[idxCt[0]:]):
            B = np.append(B, B[-1])
        delta_dot[idxCt[0]:] = B
        Ftc = np.zeros(len(idxCt))
        for i in range(len(idxCt)):
            idx = idxCt[0] + np.arange(1, i)
            Ftc[i] = geom_coeff * E0 * np.sum(delta_Uto_dot[idx]*np.flipud(time_[idx])**(-betaE))
        idx_min_phi0 = np.zeros(len(idxCt))
        Frc = np.zeros(len(idxCt))
        for j in range(idx_tm+1, idx_tm+len(idxCt)):
            phi0 = np.flipud(np.cumsum(np.flipud(time_[j-1:idxCt[1]-1:-1]**(-betaE)*delta_dot[idxCt[1]+1:j+1]), axis=0))
            phi0 = phi0[:len(idxCt)]
            idx_min_phi0 = np.argmin(np.abs(phi0))
            idxCr0 = np.arange(j+1, j-idx_min_phi0+1, -1)
            t10 = time_[idxCr0]
            idx = np.arange(idxCt[0]+1, idxCt[0]+idx_min_phi0+1)
            Frc[j-idx_tm-1] = geom_coeff * E0 * np.trapz(delta_Uto_dot[idx]*t10**(-betaE))
        return np.r_[Ftc+v0t*vdrag, Frc-v0r*vdrag]+F0
    
    def objective(self, time, t0, E0, tc, betaE, F0, F, delta, modelFt, vdrag, idx_tm=None, smooth_w=None):
        # Get indenter shape coefficient and exponent
        geom_coeff, geom_exp = get_coeff(self.ind_geom, self.tip_parameter, self.poisson_ratio)
        # Shift time using t at contact.
        time=time-tc
        # Compute deltat.
        deltat=time[1]-time[0]
        # If no t max index is given search the index of F max.
        if idx_tm is None:
            idx_tm = np.argmax(F)
        # Get t max value.
        tm = time[idx_tm]
        # Determine non contact trace region.
        idxNCt=np.where(time<0)[0]
        # Determine contact trace region
        idxCt=np.where(time>=0)[0]
        # Get indices corresponding to contact trace region.
        # Including t max.
        idxCt = np.arange(idxCt[0], idx_tm + 1)
        # Determine contact time trace.
        ttc=time[idxCt]
        # Define range to compute trace speed.
        # Including t max.
        range_v0t=np.arange((idx_tm-int(len(ttc)*3/4)), idx_tm)
        # Define range to compute retrace speed.
        # Excluding t max.
        range_v0r=np.arange(idx_tm+2, (idx_tm+1+int(len(ttc)*3/4)))
        # Fit 1 degree polynomial (x0 + m) to trace and retrace for determining
        # the corresponding speeds (x0)
        v0t = np.polyfit(time[range_v0t], delta[range_v0t], 1)[0]
        v0r = -1 * np.polyfit(time[range_v0r], delta[range_v0r], 1)[0]
        # Compute mean speed.
        v0=(v0r+v0t)/2
        # Compute retrace contact time.
        # TO DO: ADD REFERENCE TO ARTICLE!!!!
        tcr=(1+v0r/v0t)**(1/(1-betaE))/((1+v0r/v0t)**(1/(1-betaE))-1)*tm
        # If the retrace contact time is smaller than t max,
        # define the end of the contact retrace region as 3 times t max.
        if not tcr<tm:
            idxCr=np.where((time>tm) & (time<=tcr))[0]
        else:
            idxCr=np.where((time>tm) & (time<=3*tm))[0]
        # Define in contact retrace region.
        trc=time[idxCr]
        # Compute t1
        # TO DO: ADD REFERENCE TO ARTICLE!!!!
        t1=trc-(1+v0r/v0t)**(1/(1-betaE))*(trc-tm)
        # Select only the values larger than 0 of t1.
        t1=t1[t1>0]
        # Select the region of retrace time where t1 is larger than 0.
        trc=trc[t1>0]
        # Select the retrace contact indices corresponding to the retrace
        # time region where t1 is larger than 0. 
        idxCr=idxCr[:len(trc)]
        # Assign the value of F0 to the non contact region.
        FtNC=F0*np.ones(idxNCt.size)
        # Compute Force according to the selected mode:
        if modelFt == 'analytical':
            FJ = self.SolveAnalytical(
                ttc, trc, t1, self.ind_geom, geom_coeff, v0t, v0r, v0, E0, betaE, t0, F0, vdrag
            )
        elif modelFt == 'numerical':
            FJ = self.SolveNumerical(
                delta, time, geom_coeff, geom_exp, v0t, v0r, E0, betaE, F0, vdrag, smooth_w, idx_tm, idxCt, idxCr
            )
        else:
            print(f'The modelFt {modelFt} is not supported. Current valid modelFt: analytical, numerical.')
        # Determine non contact retrace region.
        idxNCr=np.arange((len(FJ)+len(FtNC)+1),len(delta)+1)
        # Assign the value of F0 to the non contact region.
        FrNC=F0*np.ones(idxNCr.size)
        # Concatenate non contact regions to the contact region. And return.
        return np.r_[FtNC+v0t*vdrag, FJ, FrNC-v0r*vdrag]
    
    def fit(self, time, F, delta, idx_tm=None, smooth_w=None):
        # Use log to make params scale more equal during fit?
        # Param order:
        # delta0, E0, f0, slope
        p0 = [self.t0_init, self.E0_init, self.tc_init, self.betaE_init, self.F0_init]
        self.n_params = len(p0)
        bounds = [
            [self.t0_min, self.E0_min, self.betaE_min, self.F0_min],
            [self.t0_max, self.E0_max, self.betaE_max, self.F0_max]
        ]
        fixed_params = {
            'F': F,
            'delta': delta,
            'modelFt': self.modelFt,
            'vdrag': self.vdrag,
            'smooth_w': smooth_w,
            'idx_tm': idx_tm
        }
        tingmodel =\
            lambda time, t0, E0, tc, betaE, F0: self.objective(self, time, t0, E0, tc, betaE, F0, **fixed_params)
        # Do fit
        res, _ = curve_fit(
            tingmodel, time, F, p0, bounds=bounds,
            method='trf', ftol=1e-08, xtol=1e-08, gtol=1e-08)

        # Assign fit results to model params
        self.t0 = res[0]
        self.E0 = res[1]
        self.tc = res[2]
        self.betaE = res[3]
        self.F0 = res[4]
        
        # Get goodness of fit params
        redchi = self.get_red_chisq(time, F, delta, idx_tm, smooth_w)

        return res, redchi

    def eval(self, time, F, delta, idx_tm=None, smooth_w=None):
        return self.objective(
            time, self.t0, self.E0, self.tc, self.betaE, self.F0, F, delta,
            self.ind_geom, self.modelFt, self.vdrag, idx_tm, smooth_w)

    def get_chisq(self, time, F, delta, y, idx_tm=None, smooth_w=None):
        return np.sum(((y - self.eval(time, F, delta, idx_tm, smooth_w))/np.std(y))**2)
    
    def get_red_chisq(self, time, F, delta, y, idx_tm=None, smooth_w=None):
        return self.get_chisq(time, F, delta, y, idx_tm, smooth_w) / self.n_params