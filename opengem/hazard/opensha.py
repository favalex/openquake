"""
Top-level managers for hazard computation.
"""

import os

import numpy

from opengem import hazard
from opengem import java
from opengem import job
from opengem.job import mixins
from opengem.hazard import job
from opengem import kvs
from opengem import settings
from opengem.logs import LOG

JAVA_CLASSES = {
    'CommandLineCalculator' : "org.gem.engine.CommandLineCalculator",
    'KVS' : "org.gem.engine.hazard.memcached.Cache",
    'JsonSerializer' : "org.gem.JsonSerializer",
    "EventSetGen" : "org.gem.calc.StochasticEventSetGenerator",
    "Random" : "java.util.Random",
    "GEM1ERF" : "org.gem.engine.hazard.GEM1ERF",
    "HazardCalculator" : "org.gem.calc.HazardCalculator",
    "Properties" : "java.util.Properties",
    "CalculatorConfigHelper" : "org.gem.engine.CalculatorConfigHelper",
    "Configuration" : "org.apache.commons.configuration.Configuration",
    "ConfigurationConverter" : "org.apache.commons.configuration.ConfigurationConverter",
    "ArbitrarilyDiscretizedFunc" : "org.opensha.commons.data.function.ArbitrarilyDiscretizedFunc",
    "ArrayList" : "java.util.ArrayList",
    "GmpeLogicTreeData" : "org.gem.engine.GmpeLogicTreeData",
    "AttenuationRelationship" : "org.opensha.sha.imr.AttenuationRelationship",
    "EqkRupForecastAPI" : "org.opensha.sha.earthquake.EqkRupForecastAPI",
    "DoubleParameter" : "org.opensha.commons.param.DoubleParameter",
    "StringParameter" : "org.opensha.commons.param.StringParameter",
    "ParameterAPI" : "org.opensha.commons.param.ParameterAPI",
}

def jclass(class_key):
    jpype = java.jvm()
    return jpype.JClass(JAVA_CLASSES[class_key])


class MonteCarloMixin:
    def preload(fn):
        """A decorator for preload steps that must run on the Jobber"""
        def preloader(self, *args, **kwargs):
            assert(self.base_path)
            # Slurp related files here...
            # TODO(JMC): No reason to give java the whole config file
            # Just the ERF LT file should do it...
            #erf_logic_tree_file = guarantee_file(self.base_path, 
            #            self.params['ERF_LOGIC_TREE_FILE'])
            
            self.store_source_model(self.config_file)
            self.store_gmpe_map(self.config_file)
            fn(self, *args, **kwargs)
        
        return preloader
        
        raise Exception("Can only handle Monte Carlo Hazard mode right now.")

    def store_source_model(self, config_file):
        """Generates an Earthquake Rupture Forecast, using the source zones and
        logic trees specified in the job config file. Note that this has to be
        done using the file itself, since it has nested references to other files.
    
        job_file should be an absolute path.
        """
        
        jpype = java.jvm()
        
        engine = jclass("CommandLineCalculator")(config_file)
        key = kvs.generate_product_key(self.id, hazard.SOURCE_MODEL_TOKEN)
        LOG.debug("Storing source model at %s" % (key))
        cache = jclass("KVS")(settings.MEMCACHED_HOST, settings.MEMCACHED_PORT)
        engine.sampleAndSaveERFTree(cache, key)
    
    def _get_command_line_calc(self):
        jpype = java.jvm()
        cache = jclass("KVS")(settings.MEMCACHED_HOST, settings.MEMCACHED_PORT)
        key = self.key
        engine = jclass("CommandLineCalculator")(cache, key)
        return engine
    
    
    def store_gmpe_map(self, config_file):
        """Generates a hash of tectonic regions and GMPEs, using the logic tree
        specified in the job config file.
        
        In the future, this file *could* be passed as a string, since it does 
        not have any included references."""
        jpype = java.jvm()  
        
        engine = jclass("CommandLineCalculator")(config_file)
        key = kvs.generate_product_key(self.id, hazard.GMPE_TOKEN)
        cache = jclass("KVS")(settings.MEMCACHED_HOST, settings.MEMCACHED_PORT)
        engine.sampleAndSaveGMPETree(cache, key)

    
    @preload
    def execute(self):
        # Chop up subregions
        # For each subregion, take a subset of the source model
        # 
        # Spawn task for subregion, sending in source-subset and 
        # GMPE subset
        pass
        
    def generate_erf(self):
        jpype = java.jvm()
        erfclass = jclass("GEM1ERF")
        
        key = kvs.generate_product_key(self.id, hazard.SOURCE_MODEL_TOKEN)
        cache = jclass("KVS")(settings.MEMCACHED_HOST, settings.MEMCACHED_PORT)
        sources = jclass("JsonSerializer").getSourceListFromCache(cache, key)
        timespan = self.params['INVESTIGATION_TIME']
        return erfclass.getGEM1ERF(sources, jpype.JDouble(float(timespan)))

    def generate_gmpe_map(self):
        key = kvs.generate_product_key(self.id, hazard.GMPE_TOKEN)
        cache = jclass("KVS")(settings.MEMCACHED_HOST, settings.MEMCACHED_PORT)
        
        gmpe_map = jclass("JsonSerializer").getGmpeMapFromCache(cache,key)
        LOG.debug("gmpe_map: %s" % gmpe_map.__class__)
        return gmpe_map

    def set_gmpe_params(self, gmpe_map):
        jpype = java.jvm()
        
        # gmpeLogicTreeData = jclass("GmpeLogicTreeData")
        # gmpeLogicTreeData =                     new GmpeLogicTreeData(kvs,
        #                     ConfigItems.GMPE_LOGIC_TREE_FILE.name(), component,
        #                     intensityMeasureType, period, damping,
        #                     gmpeTruncationType, truncationLevel,
        #                     standardDeviationType, referenceVs30Value);
                            # new GmpeLogicTreeData(relativePath, component,
                            # intensityMeasureType, period, damping,
                            # gmpeTruncationType, truncationLevel,
                            # standardDeviationType, referenceVs30Value);
        
        for trt in gmpe_map.keySet():
            gmpe = gmpe_map.get(trt)
            print "gmpe type: %s " % (gmpe.__class__)
            gmpeLogicTreeData = self._get_command_line_calc().createGmpeLogicTreeData()
            gmpeLogicTreeData.setGmpeParams(self.params['COMPONENT'], 
                self.params['INTENSITY_MEASURE_TYPE'], 
                jpype.JDouble(float(self.params['PERIOD'])), 
                jpype.JDouble(float(self.params['DAMPING'])), 
                self.params['GMPE_TRUNCATION_TYPE'], 
                jpype.JDouble(float(self.params['TRUNCATION_LEVEL'])), 
                self.params['STANDARD_DEVIATION_TYPE'], 
                jpype.JDouble(float(self.params['REFERENCE_VS30_VALUE'])), 
                jpype.JObject(gmpe, jclass("AttenuationRelationship")))
                # String component, String intensityMeasureType,
                # double period, double damping, String truncType, double truncLevel,
                # String stdType, double vs30, AttenuationRelationship ar
            gmpe_map.put(trt,gmpe)
    
    def load_ruptures(self):
        
        erf = self.generate_erf()
        
        seed = 0 # TODO(JMC): Real seed please
        rn = jclass("Random")(seed)
        event_set_gen = jclass("EventSetGen")
        self.ruptures = event_set_gen.getStochasticEventSetFromPoissonianERF(
                            erf, rn)
    
    def get_IML_list(self):
        """Build the appropriate Arbitrary Discretized Func from the IMLs,
        based on the IMT"""
        jpype = java.jvm()
        
        iml_vals = {'PGA' : numpy.log,
                    'MMI' : lambda iml: iml,
                    'PGV' : numpy.log,
                    'PGD' : numpy.log,
                    'SA' : numpy.log,
                     }
        
        iml_list = jclass("ArrayList")()
        for val in self.params['INTENSITY_MEASURE_LEVELS'].split(","):
            iml_list.add(
                iml_vals[self.params['INTENSITY_MEASURE_TYPE']](
                float(val)))
        LOG.debug("Raw IMLs: %s" % self.params['INTENSITY_MEASURE_LEVELS'])
        LOG.debug("IML_list: %s" % iml_list)
        # TODO(JMC): This looks wrong
        return iml_list

    def parameterize_sites(self, site_list):
        jpype = java.jvm()
        jsite_list = jclass("ArrayList")()
        for x in site_list:
            site = x.to_java()
            vs30 = jclass("DoubleParameter")(jpype.JString("Vs30"), 
                float(self.params['REFERENCE_VS30_VALUE']))
            site.addParameter(jpype.JObject(vs30, jclass("ParameterAPI")))
            site.addParameter(jclass("DoubleParameter")(
                    "Depth 2.5 km/sec",
                    float(self.param['REFERENCE_DEPTH_TO_2PT5KM_PER_SEC_PARAM'])))
            site.addParameter(jclass("StringParameter")("Sadigh Site Type",
                    self.params['SADIGH_SITE_TYPE']))
            jsite_list.add(site)
        return jsite_list

    def compute_hazard_curve(self, site_list):
        """Actual hazard curve calculation, runs on the workers.
        Takes a list of Site objects."""
        jpype = java.jvm()

        erf = self.generate_erf()
        gmpe_map = self.generate_gmpe_map()
        self.set_gmpe_params(gmpe_map)

        # configuration_helper = jclass("CalculatorConfigHelper")
        # configuration = jclass("ConfigurationConverter").getConfiguration(configuration_properties)

        ## here the site list should be the one appropriate for each worker. Where do I get it?
        ## this method returns a map relating sites with hazard curves (described as DiscretizedFuncAPI)
        
        # TODO(JMC): This looks wrong - this is IML list, not site_list!
        # site_list = configuration_helper.makeImlDoubleList(configuration)
        ch_iml = self.get_IML_list()
        integration_distance = jpype.JDouble(float(self.params['MAXIMUM_DISTANCE']))
        jsite_list = self.parameterize_sites(site_list)
        LOG.debug("jsite_list: %s" % jsite_list)
        # TODO(JMC): There's Java code for this already, sets each site to have
        # The same default parameters
        
        # hazard curves are returned as Map<Site, DiscretizedFuncAPI>
        hazardCurves = jclass("HazardCalculator").getHazardCurves(
            jsite_list, #
            erf,
            gmpe_map,
            ch_iml,
            integration_distance)

        # from hazard curves, probability mass functions are calculated
        pmf = jClass("org.opensha.commons.data.function.DiscretizedFuncAPI")
        pmf_calculator = jClass("org.gem.calc.ProbabilityMassFunctionCalc")
        for site in hazardCurves.keySet():
            pmf = pmf_calculator.getPMF(hazardCurves.get(site))
            hazardCurves.put(site,pmf)
           

    def compute_ground_motion_fields(self, site_id):
        """Ground motion field calculation, runs on the workers."""
        jpype = java.jvm()

        erf = self.generate_erf()
        gmpe_map = self.generate_gmpe_map()
        self.set_gmpe_params(gmpe_map)

        configuration_helper = jclass("CalculatorConfigHelper")
        configuration = jclass("ConfigurationConverter").getConfiguration(configuration_properties)
        site_lits = configuration_helper.makeImlDoubleList(configuration)

        seed = 0 # TODO(JMC): Real seed please
        rn = jclass("Random")(seed)
    
        # ground motion fields are returned as Map<EqkRupture, Map<Site, Double>>
        # that can then be serialized to cache using Roland's code
        ground_motion_fields = jclass("HazardCalculator").getGroundMotionFields(
            site_lits, erf, gmpe_map, rn)


job.HazJobMixin.register("Monte Carlo", MonteCarloMixin)


def guarantee_file(base_path, file_spec):
    """Resolves a file_spec (http, local relative or absolute path, git url,
    etc.) to an absolute path to a (possibly temporary) file."""
    # TODO(JMC): Parse out git, http, or full paths here...
    return os.path.join(base_path, file_spec)