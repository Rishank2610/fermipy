import copy
import os
import numpy as np
import fermipy.config
import fermipy.defaults as defaults
import fermipy.utils as utils
from fermipy.utils import Map
from fermipy.logger import Logger
from fermipy.logger import logLevel as ll


def poisson_lnl(nc, mu):
    nc = np.array(nc, ndmin=1)
    mu = np.array(mu, ndmin=1)

    shape = max(nc.shape, mu.shape)

    lnl = np.zeros(shape)
    mu = mu * np.ones(shape)
    nc = nc * np.ones(shape)

    msk = nc > 0

    lnl[msk] = nc[msk] * np.log(mu[msk]) - mu[msk]
    lnl[~msk] = -mu[~msk]
    return lnl


def smooth(m, k, cpix, mode='constant', threshold=0.01):
    from scipy import ndimage

    o = np.zeros(m.shape)
    for i in range(m.shape[0]):

        ks = k[i, :, :]

        mx = ks[cpix[0], :] > ks[cpix[0], cpix[1]] * threshold
        my = ks[:, cpix[1]] > ks[cpix[0], cpix[1]] * threshold

        nx = max(3, np.round(np.sum(mx) / 2.))
        ny = max(3, np.round(np.sum(my) / 2.))

        sx = slice(cpix[0] - nx, cpix[0] + nx + 1)
        sy = slice(cpix[1] - ny, cpix[1] + ny + 1)

        ks = ks[sx, sy]

        origin = [0, 0]
        if ks.shape[0] % 2 == 0: origin[0] += 1
        if ks.shape[1] % 2 == 0: origin[1] += 1

        o[i, :, :] = ndimage.convolve(m[i, :, :], ks, mode=mode,
                                      origin=origin, cval=0.0)

    #    o /= np.sum(k**2)
    return o

class ResidMapGenerator(fermipy.config.Configurable):
    """This class generates spatial residual maps from the difference
    of data and model maps smoothed with a user-defined
    spatial/spectral template.  The resulting map of source
    significance can be interpreted in the same way as the TS map (the
    likelihood of a source at the given location).  The algorithm
    approximates the best-fit source amplitude that would be derived
    from a least-squares fit to the data."""

    defaults = dict(defaults.residmap.items(),
                    fileio=defaults.fileio,
                    logging=defaults.logging)

    def __init__(self, config, gta, **kwargs):
        #        super(ResidMapGenerator,self).__init__(config,**kwargs)
        fermipy.config.Configurable.__init__(self, config, **kwargs)
        self._gta = gta
        self.logger = Logger.get(self.__class__.__name__,
                                 self.config['fileio']['logfile'],
                                 ll(self.config['logging']['verbosity']))

    def get_source_mask(self, name, kernel=None):

        sm = []
        zs = 0
        for c in self._gta.components:
            z = c.model_counts_map(name).counts.astype('float')
            if kernel is not None:
                shape = (z.shape[0],) + kernel.shape
                z = np.apply_over_axes(np.sum, z, axes=[1, 2]) * np.ones(
                    shape) * kernel[np.newaxis, :, :]
                zs += np.sum(z)
            else:
                zs += np.sum(z)

            sm.append(z)

        sm2 = 0
        for i, m in enumerate(sm):
            sm[i] /= zs
            sm2 += np.sum(sm[i] ** 2)

        for i, m in enumerate(sm):
            sm[i] /= sm2

        return sm

    def run(self, prefix, **kwargs):

        models = kwargs.get('models', self.config['models'])

        o = []

        for m in models:
            self.logger.info('Generating Residual map')
            self.logger.info(m)
            o += [self.make_residual_map(copy.deepcopy(m), prefix, **kwargs)]

        return o

    def make_residual_map(self, src_dict, prefix, exclude=None, **kwargs):

        exclude = exclude

        # Put the test source at the pixel closest to the ROI center
        xpix, ypix = (np.round((self._gta.npix - 1.0) / 2.),
                      np.round((self._gta.npix - 1.0) / 2.))
        cpix = np.array([xpix, ypix])

        skywcs = self._gta._skywcs
        skydir = utils.pix_to_skydir(cpix[0], cpix[1], skywcs)

        src_dict['ra'] = skydir.ra.deg
        src_dict['dec'] = skydir.dec.deg
        src_dict.setdefault('SpatialModel', 'PointSource')
        src_dict.setdefault('SpatialWidth', 0.3)
        src_dict.setdefault('Index', 2.0)

        kernel = None

        if src_dict['SpatialModel'] == 'Gaussian':
            kernel = utils.make_gaussian_kernel(src_dict['SpatialWidth'],
                                                cdelt=self._gta.components[
                                                    0].binsz,
                                                npix=101)
            kernel /= np.sum(kernel)
            cpix = [50, 50]

        self._gta.add_source('testsource', src_dict, free=True,
                             init_source=False)
        src = self._gta.roi.get_source_by_name('testsource', True)

        modelname = utils.create_model_name(src)

        enumbins = self._gta.enumbins
        npix = self._gta.components[0].npix

        mmst = np.zeros((npix, npix))
        cmst = np.zeros((npix, npix))
        emst = np.zeros((npix, npix))

        sm = self.get_source_mask('testsource', kernel)
        ts = np.zeros((npix, npix))
        sigma = np.zeros((npix, npix))
        excess = np.zeros((npix, npix))

        self._gta.delete_source('testsource')

        for i, c in enumerate(self._gta.components):
            mc = c.model_counts_map(exclude=exclude).counts.astype('float')
            cc = c.counts_map().counts.astype('float')
            ec = np.ones(mc.shape)

            ccs = smooth(cc, sm[i], cpix)
            mcs = smooth(mc, sm[i], cpix)
            ecs = smooth(ec, sm[i], cpix)

            cms = np.sum(ccs, axis=0)
            mms = np.sum(mcs, axis=0)
            ems = np.sum(ecs, axis=0)

            cmst += cms
            mmst += mms
            emst += ems

            cts = 2.0 * (poisson_lnl(cms, cms) - poisson_lnl(cms, mms))
            excess += cms - mms

        ts = 2.0 * (poisson_lnl(cmst, cmst) - poisson_lnl(cmst, mmst))
        sigma = np.sqrt(ts)
        sigma[excess < 0] *= -1

        sigma_map_file = utils.format_filename(self.config['fileio']['workdir'],
                                               'residmap_sigma.fits',
                                               prefix=[prefix, modelname])

        data_map_file = utils.format_filename(self.config['fileio']['workdir'],
                                              'residmap_data.fits',
                                              prefix=[prefix, modelname])

        model_map_file = utils.format_filename(self.config['fileio']['workdir'],
                                               'residmap_model.fits',
                                               prefix=[prefix, modelname])

        excess_map_file = utils.format_filename(self.config['fileio']['workdir'],
                                                'residmap_excess.fits',
                                                prefix=[prefix, modelname])

        emst /= np.max(emst)

        utils.write_fits_image(sigma, skywcs, sigma_map_file)
        utils.write_fits_image(cmst / emst, skywcs, data_map_file)
        utils.write_fits_image(mmst / emst, skywcs, model_map_file)
        utils.write_fits_image(excess / emst, skywcs, excess_map_file)

        files = {'sigma': os.path.basename(sigma_map_file),
                 'model': os.path.basename(model_map_file),
                 'data': os.path.basename(data_map_file),
                 'excess': os.path.basename(excess_map_file)}

        o = {'name': '%s_%s' % (prefix, modelname),
             'files': files,
             'wcs': skywcs,
             'sigma': Map(sigma, skywcs),
             'model': Map(mmst / emst, skywcs),
             'data': Map(cmst / emst, skywcs),
             'excess': Map(excess / emst, skywcs)}

        return o
