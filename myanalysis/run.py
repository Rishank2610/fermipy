from fermipy.gtanalysis import GTAnalysis

gta = GTAnalysis('config.yaml',logging={'verbosity' : 3})

gta.setup()

gta.write_roi('fit0')

gta.optimize()

gta.print_roi()

gta.write_roi('fit1')

gta.free_sources(distance=3.0,pars='norm')

gta.free_source('galdiff')
gta.free_source('isodiff')
gta.free_source('1ES1218+304')

gta.fit()

gta.write_roi('fit2',make_plots=True)

#model = {'SpatialModel' : 'PointSource', 'Index' : 2.0,
#         'SpectrumType' : 'PowerLaw'}

# Both methods return a dictionary with the maps
m0 = gta.residmap('fit2', model=model, make_plots=True)
m1 = gta.tsmap('fit2', model=model, make_plots=True)

m0 = gta.residmap('fit2', make_plots=True)
m1 = gta.tsmap('fit2', make_plots=True)

gta.sed('1ES1218+304', make_plots=True)
