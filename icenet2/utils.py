import os
import sys
import warnings
import numpy as np
from datetime import datetime
sys.path.insert(0, os.path.join(os.getcwd(), 'icenet2'))  # if using jupyter kernel
import config
import misc
from dateutil.relativedelta import relativedelta
import tensorflow as tf
import xarray as xr
import iris
import cartopy.crs as ccrs
import pandas as pd
import regex as re
import json
import time


###############################################################################
############### DATA PROCESSING & LOADING
###############################################################################


class IceNet2DataPreProcessor(object):
    """
    Normalises IceNet2 input data and saves the normalised daily averages
    as .npy files.

    Data is stored in the following form:
     - data/network_datasets/dataset_name/obs/tas/2006_04_12.npy
    """

    def __init__(self, dataset_name, preproc_vars, preproc_hemispheres, obs_train_dates,
                 minmax, verbose_level, raw_data_shape,
                 dtype=np.float32):
        """
        Parameters:
        dataset_name (str): Name of this network dataset (used for the folder to
        store data)

        preproc_vars (dict): Which variables to preprocess. Example:

                preproc_vars = {
                    'siconca': {'anom': True, 'abs': True},
                    'tas': {'anom': True, 'abs': False},
                    'tos': {'anom': True, 'abs': False},
                    'rsds': {'anom': True, 'abs': False},
                    'rsus': {'anom': True, 'abs': False},
                    'psl': {'anom': False, 'abs': True},
                    'zg500': {'anom': False, 'abs': True},
                    'zg250': {'anom': False, 'abs': True},
                    'ua10': {'anom': False, 'abs': True},
                    'uas': {'anom': False, 'abs': True},
                    'vas': {'anom': False, 'abs': True},
                    'sfcWind': {'anom': False, 'abs': True},
                    'land': {'metadata': True, 'include': True},
                    'circday': {'metadata': True, 'include': True}
                }

        preproc_hemispheres (list): Which hemispheres to preprocess
        options: ('nh' and 'sh')

        obs_train_dates (tuple): Tuple of months (stored as datetimes)
        to be used for the training set by the data loader.

        minmax (bool): Whether to use min-max normalisation to (-1, 1)

        verbose_level (int): Controls how much to print. 0: Print nothing.
        1: Print key set-up stages. 2: Print debugging info.

        raw_data_shape (tuple): Shape of input satellite data as (rows, cols).

        dtype (type): Data type for the data (default np.float32)

        """
        self.dataset_name = dataset_name
        self.preproc_hemispheres = preproc_hemispheres
        self.preproc_vars = preproc_vars
        self.obs_train_dates = obs_train_dates
        self.minmax = minmax
        self.verbose_level = verbose_level
        self.raw_data_shape = raw_data_shape
        self.dtype = dtype

        self.set_up_folder_hierarchy()
        self.preproc_and_save_icenet_data()

        if self.verbose_level >= 1:
            print("Setup complete.\n")

    def set_up_folder_hierarchy(self):

        """
        Initialise the folders to store the datasets.
        """

        if self.verbose_level >= 1:
            print('Setting up the folder hierarchy for {}... '.format(self.dataset_name),
                  end='', flush=True)

        # Root folder for this dataset
        self.dataset_path = os.path.join('data', 'network_datasets', self.dataset_name)

        # Dictionary data structure to store folder paths
        self.paths = {}

        for hemisphere in self.preproc_hemispheres:

            self.paths[hemisphere] = {}

            # Set up the folder hierarchy
            self.paths[hemisphere]['obs'] = {}

            for varname, vardict in self.preproc_vars.items():

                if 'metadata' not in vardict.keys():
                    self.paths[hemisphere]['obs'][varname] = {}

                    for data_format in vardict.keys():

                        if vardict[data_format] is True:
                            path = os.path.join(self.dataset_path, hemisphere, 'obs',
                                                varname, data_format)

                            self.paths[hemisphere]['obs'][varname][data_format] = path

                            if not os.path.exists(path):
                                os.makedirs(path)

                elif 'metadata' in vardict.keys():

                    if vardict['include'] is True:
                        path = os.path.join(self.dataset_path, hemisphere, 'meta')

                        self.paths[hemisphere]['meta'] = path

                        if not os.path.exists(path):
                            os.makedirs(path)

        if self.verbose_level >= 1:
            print('Done.')

    @staticmethod
    def mean_and_std(list, verbose_level=2):

        """
        Return the mean and standard deviation of an array-like object (intended
        use case is for normalising a raw satellite data array based on a list
        of samples used for training).
        """

        mean = np.nanmean(list)
        std = np.nanstd(list)

        if verbose_level >= 2:
            print("Mean: {:.3f}, std: {:.3f}".format(mean.item(), std.item()))

        return mean, std

    def normalise_array_using_all_training_data(self, da, minmax=False,
                                                mean=None, std=None,
                                                min=None, max=None):

        """
        Using the *training* data only, compute the mean and
        standard deviation of the input raw satellite DataArray (`da`)
        and return a normalised version. If minmax=True,
        instead normalise to lie between min and max of the elements of `array`.

        If min, max, mean, or std are given values other than None,
        those values are used rather than being computed from the training months.

        Returns:
        new_da (xarray.DataArray): Normalised array.

        mean, std (float): Mean and standard deviation used or computed for the
        normalisation.

        min, max (float): Min and max used or computed for the normalisation.
        """

        training_samples = da.sel(time=self.obs_train_dates).data
        training_samples = training_samples.ravel()

        if not minmax:
            # Normalise by mean and standard deviation (compute them if not provided)

            if mean is None and std is None:
                # Compute mean and std
                mean, std = IceNet2DataPreProcessor.mean_and_std(training_samples,
                                                                 self.verbose_level)
            elif mean is not None and std is None:
                # Compute std only
                _, std = IceNet2DataPreProcessor.mean_and_std(training_samples,
                                                              self.verbose_level)
            elif mean is None and std is not None:
                # Compute mean only
                mean, _ = IceNet2DataPreProcessor.mean_and_std(training_samples,
                                                               self.verbose_level)

            new_da = (da - mean) / std

        elif minmax:
            # Normalise by min and max (compute them if not provided)

            if min is None:
                min = np.nanmin(training_samples)
            if max is None:
                max = np.nanmax(training_samples)

            new_da = (da - min) / (max - min)

        if minmax:
            return new_da, min, max
        elif not minmax:
            return new_da, mean, std

    def save_xarray_in_daily_averages(self, da, dataset_type, hemisphere, varname, data_format,
                                      member_id=None):

        """
        Saves an xarray DataArray as daily averaged .npy files using the
        self.paths data structure.

        Parameters:
        da (xarray.DataArray): The DataArray to save.

        dataset_type (str): Either 'obs' or 'transfer' (for CMIP6 data) - the type
        of dataset being saved.

        varname (str): Variable name being saved.

        data_format (str): Either 'abs' or 'anom' - the format of the data
        being saved.
        """

        if self.verbose_level >= 2:
            print('Saving {} {} daily averages... '.format(data_format, varname), end='', flush=True)

        for date in da.time.values:
            slice = da.sel(time=date).data
            date_datetime = datetime.utcfromtimestamp(date.tolist() / 1e9)
            fname = date_datetime.strftime('%Y_%m_%d.npy')

            if dataset_type == 'obs':
                np.save(os.path.join(self.paths[hemisphere][dataset_type][varname][data_format], fname),
                        slice)

        if self.verbose_level >= 2:
            print('Done.')

    def open_dataarray_from_files(self, hemisphere, varname, data_format):

        """
        Open the yearly xarray files, accounting for some ERA5 variables that have
        erroneous 'unknown' NetCDF variable names which prevents concatentation.
        """

        daily_folder = os.path.join('data', hemisphere, varname)

        # Open all the NetCDF files in the given variable folder
        netcdf_regex = re.compile('^.*\\.nc$'.format(varname))
        filenames = sorted(os.listdir(daily_folder))  # List of files in month folder
        filenames = [filename for filename in filenames if netcdf_regex.match(filename)]
        paths = [os.path.join(daily_folder, filename) for filename in filenames]

        ds_list = [xr.open_dataset(path) for path in paths]

        # Set of variables names
        varset = set([next(iter(xr.open_dataset(path).data_vars.values())).name for path in paths])
        if 'unknown' in list(varset):
            warnings.warn('warning: renaming erroneous "unknown" variable for concatenation')

            varset.remove('unknown')
            real_varname = next(iter(varset))

            renamed_ds_list = []
            for ds in ds_list:
                varnames = [da.name for da in iter(ds.data_vars.values())]
                if 'unknown' in varnames:
                    ds = ds.rename({'unknown': real_varname})
                renamed_ds_list.append(ds)

            ds_list = renamed_ds_list

        ds = xr.combine_nested(ds_list, concat_dim='time')

        da = next(iter(ds.data_vars.values()))
        if len(ds.data_vars) > 1:
            warnings.warn('warning: there is more than one variable in the netcdf '
                          'file, but it is assumed that there is only one.')
            print('the loaded variable is: {}'.format(da.name))

        return da

    def save_variable(self, hemisphere, varname, data_format, dates=None):

        """
        Save a normalised 3-dimensional satellite/reanalysis dataset as daily
        averages (either the absolute values or the daily anomalies
        computed with xarray).

        This method assumes there is only one variable stored in the NetCDF files.

        Parameters:
        hemisphere (str): 'nh' or 'sh'

        varname (str): Name of the variable to load & save

        data_format (str): 'abs' for absolute values, or 'anom' to compute the
        anomalies, or 'linear_trend' for SIC linear trend projections.

        dates (list of datetime): Months to use to compute the daily
        climatologies (defaults to the months used for training).
        """

        if data_format == 'anom':
            if dates is None:
                dates = self.obs_train_dates

        ########################################################################
        ################# Observational variable
        ########################################################################

        if self.verbose_level >= 2:
            print("Preprocessing {} hemisphere data for {} in {} format...  ".
                  format(hemisphere, varname, data_format), end='', flush=True)
            tic2 = time.time()

        # Extract the first DataArray in the dataset
        da = self.open_dataarray_from_files(hemisphere, varname, data_format)

        if data_format == 'anom':
            climatology = da.sel(time=dates).groupby('time.dayofyear', restore_coord_dims=True).mean()
            da = da.groupby('time.dayofyear') - climatology

        # Realise the array
        da.data = np.asarray(da.data, dtype=self.dtype)

        # Normalise the array
        if varname == 'siconca':
            # Don't normalsie SIC values - already betw 0 and 1
            mean, std = None, None
            min, max = None, None
        else:
            if self.minmax:
                da, min, max = self.normalise_array_using_all_training_data(da, self.minmax)
            elif not self.minmax:
                da, mean, std = self.normalise_array_using_all_training_data(da, self.minmax)

        da.data[np.isnan(da.data)] = 0.  # Convert any NaNs to zeros

        self.save_xarray_in_daily_averages(da, 'obs', hemisphere, varname, data_format)

        if self.verbose_level >= 2:
            print("Done in {:.3f}s.\n".format(time.time() - tic2))

    def preproc_and_save_icenet_data(self):

        '''
        Loop through all the desired variables, preprocessing and saving in the
        network dataset folder.
        '''

        if self.verbose_level == 1:
            print("Loading and normalising the raw input maps... ", end='', flush=True)
            tic = time.time()

        for hemisphere in self.preproc_hemispheres:

            for varname, vardict in self.preproc_vars.items():

                if 'metadata' not in vardict.keys():

                    for data_format in vardict.keys():

                        if vardict[data_format] is True:

                            self.save_variable(hemisphere, varname, data_format)

                elif 'metadata' in vardict.keys():

                    if vardict['include']:
                        if varname == 'land':
                            if self.verbose_level >= 2:
                                print("Setting up the land map: ", end='', flush=True)

                            land_mask = np.load(os.path.join('data', hemisphere, 'masks', config.fnames['land_mask']))
                            land_map = np.ones(self.raw_data_shape, self.dtype)
                            land_map[~land_mask] = -1.

                            np.save(os.path.join(self.paths[hemisphere]['meta'], 'land.npy'), land_map)

                            print('\n')

                        elif varname == 'circday':
                            if self.verbose_level >= 2:
                                print("Computing circular day values... ", end='', flush=True)
                                tic2 = time.time()

                            # 2012 used arbitrarily as leap year
                            for date in pd.date_range(start='2012-1-1', end='2012-12-31'):

                                if hemisphere == 'nh':
                                    circday = date.dayofyear
                                elif hemisphere == 'sh':
                                    circday = date.dayofyear + 365.25/2

                                cos_month = np.cos(2 * np.pi * circday / 366, dtype=self.dtype)
                                sin_month = np.sin(2 * np.pi * circday / 366, dtype=self.dtype)

                                np.save(os.path.join(self.paths[hemisphere]['meta'], date.strftime('cos_month_%m_%d.npy')), cos_month)
                                np.save(os.path.join(self.paths[hemisphere]['meta'], date.strftime('sin_month_%m_%d.npy')), sin_month)

                            if self.verbose_level >= 2:
                                print("Done in {:.3f}s.\n".format(time.time() - tic2))

        if self.verbose_level == 1:
            print("Done in {:.3f}s.\n".format(time.time() - tic))


class IceNet2DataLoader(tf.keras.utils.Sequence):
    """
    Generates batches of input-output tensors for training IceNet2. Inherits from
    keras.utils.Sequence which ensures each the network trains once on each
    sample per epoch. Must implement a __len__ method that returns the
    number of batches and a __getitem__ method that returns a batch of data. The
    on_epoch_end method is called after each epoch.

    See: https://www.tensorflow.org/api_docs/python/tf/keras/utils/Sequence

    """

    def __init__(self, data_loader_config_path, seed=None):

        with open(data_loader_config_path, 'r') as readfile:
            self.config = json.load(readfile)

        if seed is None:
            self.set_seed(self.config['default_seed'])
        else:
            self.set_seed(seed)
        self.set_forecast_IDs(dataset='train')
        self.load_missing_dates()
        self.remove_missing_dates()
        self.set_variable_path_formats()
        self.set_number_of_input_channels_for_each_input_variable()
        self.load_polarholes()
        self.determine_tot_num_channels()
        self.on_epoch_end()

        if self.config['verbose_level'] >= 1:
            print("Setup complete.\n")

    def set_forecast_IDs(self, dataset='train'):
        """
        Build up a list of forecast initialisation dates for the train, val, or
        test sets based on the configuration JSON file start & end points for
        each dataset.
        """

        self.all_forecast_IDs = []

        for hemisphere, sample_ID_dict in self.config['sample_IDs'].items():
            forecast_start_date_ends = sample_ID_dict['obs_{}_dates'.format(dataset)]

            if forecast_start_date_ends is not None:
                # Convert to Pandas Timestamps
                forecast_start_date_ends = [
                    pd.Timestamp(date).to_pydatetime() for date in forecast_start_date_ends
                ]

                forecast_start_dates = misc.filled_daily_dates(
                    forecast_start_date_ends[0],
                    forecast_start_date_ends[1])

                self.all_forecast_IDs.extend([
                    (hemisphere, start_date) for start_date in forecast_start_dates]
                )

        if dataset == 'train' or dataset == 'val':
            if '{}_sample_thin_factor'.format(dataset) in self.config.keys():
                if self.config['{}_sample_thin_factor'.format(dataset)] is not None:
                    reduce = self.config['{}_sample_thin_factor'.format(dataset)]
                    prev_n_samps = len(self.all_forecast_IDs)
                    new_n_samps = int(prev_n_samps / reduce)

                    self.all_forecast_IDs = self.rng.choice(
                        a=self.all_forecast_IDs,
                        size=new_n_samps,
                        replace=False
                    )

                    if self.config['verbose_level'] >= 1:
                        print('Number of {} samples thinned from {} '
                              'to {}.'.format(dataset, prev_n_samps, len(self.all_forecast_IDs)))

    def set_variable_path_formats(self):

        """
        Initialise the paths to the .npy files of each variable based on
        `self.config['input_data']`.
        """

        if self.config['verbose_level'] >= 1:
            print('Setting up the variable paths for {}... '.format(self.config['dataset_name']),
                  end='', flush=True)

        # Parent folder for this dataset
        self.dataset_path = os.path.join('data', 'network_datasets', self.config['dataset_name'])

        # Dictionary data structure to store image variable paths
        self.variable_paths = {}

        for hemisphere in ['sh', 'nh']:
            self.variable_paths[hemisphere] = {}
            for varname, vardict in self.config['input_data'].items():

                if 'metadata' not in vardict.keys():
                    self.variable_paths[hemisphere][varname] = {}

                    for data_format in vardict.keys():

                        if vardict[data_format]['include'] is True:

                            path = os.path.join(self.dataset_path, hemisphere, 'obs',
                                                varname, data_format, '{:04d}_{:02d}_{:02d}.npy')

                            self.variable_paths[hemisphere][varname][data_format] = path

                elif 'metadata' in vardict.keys():

                    if vardict['include'] is True:

                        if varname == 'land':
                            path = os.path.join(self.dataset_path, hemisphere, 'meta', 'land.npy')
                            self.variable_paths[hemisphere]['land'] = path

                        elif varname == 'circday':
                            path = os.path.join(self.dataset_path, hemisphere, 'meta',
                                                '{}_month_{:02d}_{:02d}.npy')
                            self.variable_paths[hemisphere]['circday'] = path

        if self.config['verbose_level'] >= 1:
            print('Done.')

    def reset_data_loader_with_new_input_data(self):
        """
        If the data loader object's `input_data` field is updated, this method
        must be called to update the other object parameters.
        """
        self.set_variable_path_formats()
        self.set_number_of_input_channels_for_each_input_variable()
        self.determine_tot_num_channels()

    def set_seed(self, seed):
        """
        Set the seed used by the random generator (used to randomly shuffle
        the ordering of training samples after each epoch).
        """
        if self.config['verbose_level'] >= 1:
            print("Setting the data generator's random seed to {}".format(seed))
        self.rng = np.random.default_rng(seed)

    def determine_variable_names(self):
        """
        Set up a list of strings for the names of each input variable (in the
        correct order) by looping over the `input_data` dictionary.
        """
        variable_names = []

        for varname, vardict in self.config['input_data'].items():
            # Input variables that span time
            if 'metadata' not in vardict.keys():
                for data_format in vardict.keys():
                    if vardict[data_format]['include']:
                        if data_format != 'linear_trend':
                            for lag in np.arange(1, vardict[data_format]['max_lag']+1):
                                variable_names.append(varname+'_{}_{}'.format(data_format, lag))
                        elif data_format == 'linear_trend':
                            for leadtime in np.arange(1, self.config['n_forecast_days']+1):
                                variable_names.append(varname+'_{}_{}'.format(data_format, leadtime))

            # Metadata input variables that don't span time
            elif 'metadata' in vardict.keys() and vardict['include']:
                if varname == 'land':
                    variable_names.append(varname)

                elif varname == 'circday':
                    variable_names.append('cos(day)')
                    variable_names.append('sin(day)')

        return variable_names

    def set_number_of_input_channels_for_each_input_variable(self):
        """
        Build up the dict `self.num_input_channels_dict` to store the number of input
        channels spanned by each input variable.
        """

        if self.config['verbose_level'] >= 1:
            print("Setting the number of input months for each input variable.")

        self.num_input_channels_dict = {}

        for varname, vardict in self.config['input_data'].items():
            if 'metadata' not in vardict.keys():
                # Variables that span time
                for data_format in vardict.keys():
                    if vardict[data_format]['include']:
                        varname_format = varname+'_{}'.format(data_format)
                        if data_format != 'linear_trend':
                            self.num_input_channels_dict[varname_format] = vardict[data_format]['max_lag']
                        elif data_format == 'linear_trend':
                            self.num_input_channels_dict[varname_format] = self.config['n_forecast_days']

            # Metadata input variables that don't span time
            elif 'metadata' in vardict.keys() and vardict['include']:
                if varname == 'land':
                    self.num_input_channels_dict[varname] = 1

                if varname == 'circday':
                    self.num_input_channels_dict[varname] = 2

    def determine_tot_num_channels(self):
        """
        Determine the number of channels for the input 3D volumes.
        """

        self.tot_num_channels = 0
        for varname, num_channels in self.num_input_channels_dict.items():
            self.tot_num_channels += num_channels

    def all_sic_input_dates_from_forecast_start_date(self, forecast_start_date):
        """
        Return a list of all the SIC dates used as input for a particular forecast
        date, based on the "max_lag" options of self.config['input_data'].
        """

        # Find all SIC lags
        max_lags = []
        if self.config['input_data']['siconca']['abs']['include']:
            max_lags.append(self.config['input_data']['siconca']['abs']['max_lag'])
        if self.config['input_data']['siconca']['anom']['include']:
            max_lags.append(self.config['input_data']['siconca']['anom']['max_lag'])
        max_lag = np.max(max_lags)

        input_dates = [
            forecast_start_date - relativedelta(days=int(lag)) for lag in np.arange(1, max_lag+1)
        ]

        return input_dates

    def check_for_missing_date_dependence(self, hemisphere, forecast_start_date):
        """
        Check a forecast ID and return a bool for whether any of the input SIC maps
        are missing. Used to remove forecast IDs that depend on missing SIC data.

        Note: If one of the _forecast_ dates are missing but not _input_ dates,
        the sample weight matrix for that date will be all zeroes so that the
        samples for that date do not appear in the loss function.
        """
        contains_missing_date = False

        # Check SIC input dates
        input_dates = self.all_sic_input_dates_from_forecast_start_date(forecast_start_date)

        for input_date in input_dates:
            if any([input_date == missing_date for missing_date in self.missing_dates[hemisphere]]):
                contains_missing_date = True
                break

        return contains_missing_date

    def load_missing_dates(self):

        '''
        Load missing SIC day spreadsheet and use it to build up a list of all
        missing days
        '''

        self.missing_dates = {}

        for hemisphere in ['nh', 'sh']:
            self.missing_dates[hemisphere] = []
            missing_date_df = pd.read_csv(
                os.path.join('data', hemisphere, config.fnames['missing_sic_days']))
            for idx, row in missing_date_df.iterrows():
                # Ensure hour = 0 convention for daily dates
                start = pd.Timestamp(row['start']).to_pydatetime().replace(hour=0)
                end = pd.Timestamp(row['end']).to_pydatetime().replace(hour=0)
                self.missing_dates[hemisphere].extend(
                    misc.filled_daily_dates(start, end, include_end=True)
                )

    def remove_missing_dates(self):

        '''
        Remove dates from self.all_forecast_start_dates that depend on a missing
        observation of SIC.
        '''

        if self.config['verbose_level'] >= 2:
            print('Checking forecast start dates for missing SIC dates... ', end='', flush=True)

        new_all_forecast_IDs = []
        for idx, (hemisphere, forecast_start_date) in enumerate(self.all_forecast_IDs):
            if self.check_for_missing_date_dependence(hemisphere, forecast_start_date):
                if self.config['verbose_level'] >= 3:
                    print('Removing {}, '.format(forecast_start_date.strftime('%Y_%m_%d')), end='', flush=True)

            else:
                new_all_forecast_IDs.append((hemisphere, forecast_start_date))

        self.all_forecast_IDs = new_all_forecast_IDs

    def load_polarholes(self):
        """
        This method loads the polar holes.
        """

        if self.config['verbose_level'] >= 1:
            tic = time.time()
            print("Loading and augmenting the polar holes... ", end='', flush=True)

        polarhole_path = os.path.join('data', 'nh', 'masks', config.fnames['polarhole1'])
        self.polarhole1_mask = np.load(polarhole_path)

        polarhole_path = os.path.join('data', 'nh', 'masks', config.fnames['polarhole2'])
        self.polarhole2_mask = np.load(polarhole_path)

        self.nopolarhole_mask = np.full((432, 432), False)

        if self.config['verbose_level'] >= 1:
            print("Done in {:.3f}s.\n".format(time.time() - tic))

    def determine_polar_hole_mask(self, hemisphere, forecast_start_date):
        """
        Determine which polar hole mask to use (if any) by finding the oldest SIC
        input month based on the current output month. The polar hole active for
        the oldest input month is used (because the polar hole size decreases
        monotonically over time, and we wish to use the largest polar hole for
        the input data).

        Parameters:
        hemisphere (str): 'sh' or 'nh'

        forecast_start_date (datetime): Timepoint for the forecast initialialisation.

        Returns:
        polarhole_mask: Mask array with NaNs on polar hole grid cells and 1s
        elsewhere.
        """

        if hemisphere == 'sh':
            polarhole_mask = self.nopolarhole_mask
            if self.config['verbose_level'] >= 3:
                print("Forecast start date: {}, polar hole: {}".format(
                    forecast_start_date.strftime("%Y_%m"), "none"))

        if hemisphere == 'nh':
            oldest_input_date = min(self.all_sic_input_dates_from_forecast_start_date(forecast_start_date))

            if oldest_input_date <= config.polarhole1_final_date:
                polarhole_mask = self.polarhole1_mask
                if self.config['verbose_level'] >= 3:
                    print("Forecast start date: {}, polar hole: {}".format(
                        forecast_start_date.strftime("%Y_%m"), 1))

            elif oldest_input_date <= config.polarhole2_final_date:
                polarhole_mask = self.polarhole2_mask
                if self.config['verbose_level'] >= 3:
                    print("Forecast start date: {}, polar hole: {}".format(
                        forecast_start_date.strftime("%Y_%m"), 2))

            else:
                polarhole_mask = self.nopolarhole_mask
                if self.config['verbose_level'] >= 3:
                    print("Forecast start date: {}, polar hole: {}".format(
                        forecast_start_date.strftime("%Y_%m"), "none"))

        return polarhole_mask

    def determine_active_grid_cell_mask(self, hemisphere, forecast_date):
        """
        Determine which active grid cell mask to use (a boolean array with
        True on active cells and False on inactive cells). The cells with 'True'
        are where predictions are to be made with IceNet. The active grid cell
        mask for a particular month is determined by the sum of the land cells,
        the ocean cells (for that month), and the missng polar hole.

        The mask is used for removing 'inactive' cells (such as land or polar
        hole cells) from the loss function in self.data_generation.
        """

        output_month_str = '{:02d}'.format(forecast_date.month)
        output_active_grid_cell_mask_fname = config.formats['active_grid_cell_mask']. \
            format(output_month_str)
        output_active_grid_cell_mask_path = os.path.join('data', hemisphere, 'masks',
                                                         output_active_grid_cell_mask_fname)
        output_active_grid_cell_mask = np.load(output_active_grid_cell_mask_path)

        # Only use the polar hole mask if predicting observational data
        polarhole_mask = self.determine_polar_hole_mask(hemisphere, forecast_date)

        # Add the polar hole mask to that land/ocean mask for the current month
        output_active_grid_cell_mask[polarhole_mask] = False

        return output_active_grid_cell_mask

    def convert_to_validation_data_loader(self):

        """
        This method resets the `all_forecast_start_dates` array to correspond to the
        validation months defined by `self.obs_val_dates`.
        """

        self.set_forecast_IDs(dataset='val')
        self.remove_missing_dates()

    def convert_to_test_data_loader(self):

        """
        As above but for the testing months defined by `self.obs_test_dates`
        """

        self.set_forecast_IDs(dataset='test')
        self.remove_missing_dates()

    def data_generation(self, forecast_IDs):
        """
        Generate input-output data for IceNet at defined indexes into the SIC
        satellite array.

        Parameters:
        forecast_IDs (list): an (N_samps,) array of tuples. The
        first element corresponds to the hemisphere of the forecast (either
        'nh' for the Arctic or 'sh' for the Antarctic), and the second element
        is a datetime object corresponding to the forecast initialisation date.

        Returns:
        X (ndarray): Set of input 3D volumes.

        y (ndarray): Set of ground truth output SIC maps with loss function pixel
        weighting as first channel.

        """

        current_batch_size = len(forecast_IDs)

        ########################################################################
        # OUTPUT LABELS
        ########################################################################

        # Build up the set of N_samps output SIC time-series
        #   (each n_forecast_days long in the time dimension)

        # To become array of shape (N_samps, *self.config['raw_data_shape'], self.config['n_forecast_days'])
        batch_sic_list = []

        for sample_idx, (hemisphere, forecast_start_date) in enumerate(forecast_IDs):

            # To become array of shape (*config['raw_data_shape'], config['n_forecast_days'])
            sample_sic_list = []

            for forecast_leadtime_idx in range(self.config['n_forecast_days']):

                forecast_target_date = forecast_start_date + relativedelta(days=forecast_leadtime_idx)

                if not os.path.exists(
                    self.variable_paths[hemisphere]['siconca']['abs'].format(
                        forecast_target_date.year,
                        forecast_target_date.month,
                        forecast_target_date.day)):
                    # Output file does not exist - fill it with NaNs
                    sample_sic_list.append(np.full(self.config['raw_data_shape'], np.nan))

                else:
                    # Output file exists
                    sample_sic_list.append(
                        np.load(self.variable_paths[hemisphere]['siconca']['abs'].format(
                            forecast_target_date.year, forecast_target_date.month, forecast_target_date.day))
                    )

            batch_sic_list.append(np.stack(sample_sic_list, axis=0))

        batch_sic = np.stack(batch_sic_list, axis=0)

        # Move day index from axis 1 to axis 3
        batch_sic = np.moveaxis(batch_sic, source=1, destination=3)

        # 'Hacky' solution for pixelwise loss function weighting: also output
        #   the pixelwise sample weights as the last channel of y
        y = np.zeros((current_batch_size,
                      *self.config['raw_data_shape'],
                      self.config['n_forecast_days'],
                      2),
                     dtype=np.float32)

        y[:, :, :, :, 0] = batch_sic

        for sample_idx, (hemisphere, forecast_start_date) in enumerate(forecast_IDs):

            for forecast_leadtime_idx in range(self.config['n_forecast_days']):

                forecast_target_date = forecast_start_date + relativedelta(days=forecast_leadtime_idx)

                if any([forecast_target_date == missing_date for missing_date in self.missing_dates[hemisphere]]):
                    sample_weight = np.zeros(self.config['raw_data_shape'], np.float32)

                else:
                    # Zero loss outside of 'active grid cells'
                    sample_weight = self.determine_active_grid_cell_mask(hemisphere, forecast_target_date)
                    sample_weight = sample_weight.astype(np.float32)

                    # Scale the loss for each month s.t. March is
                    #   scaled by 1 and Sept is scaled by 1.77
                    if self.config['loss_weight_months']:
                        sample_weight *= 33928. / np.sum(sample_weight)

                y[sample_idx, :, :, forecast_leadtime_idx, 1] = sample_weight

        ########################################################################
        # INPUT FEATURES
        ########################################################################

        # Batch tensor
        X = np.zeros((current_batch_size, *self.config['raw_data_shape'], self.tot_num_channels),
                     dtype=np.float32)

        # Build up the batch of inputs
        for sample_idx, (hemisphere, forecast_start_date) in enumerate(forecast_IDs):

            present_date = forecast_start_date - relativedelta(days=1)

            # Initialise variable indexes used to fill the input tensor `X`
            variable_idx1 = 0
            variable_idx2 = 0

            for varname, vardict in self.config['input_data'].items():

                if 'metadata' not in vardict.keys():

                    for data_format in vardict.keys():

                        if vardict[data_format]['include']:

                            varname_format = '{}_{}'.format(varname, data_format)

                            if data_format != 'linear_trend':
                                max_lag = vardict[data_format]['max_lag']
                                input_months = [present_date - relativedelta(days=int(lag))
                                                for lag in np.arange(1, max_lag+1)]
                            elif data_format == 'linear_trend':
                                input_months = [present_date + relativedelta(days=int(lead))
                                                for lead in np.arange(1, self.config['n_forecast_days']+1)]

                            variable_idx2 += self.num_input_channels_dict[varname_format]

                            X[sample_idx, :, :, variable_idx1:variable_idx2] = \
                                np.stack([np.load(self.variable_paths[hemisphere][varname][data_format].format(
                                          date.year, date.month, date.day))
                                          for date in input_months], axis=-1)

                            variable_idx1 += self.num_input_channels_dict[varname_format]

                elif 'metadata' in vardict.keys() and vardict['include']:

                    variable_idx2 += self.num_input_channels_dict[varname]

                    if varname == 'land':
                        X[sample_idx, :, :, variable_idx1] = np.load(self.variable_paths[hemisphere]['land'])

                    elif varname == 'circday':
                        # Broadcast along row and col dimensions
                        X[sample_idx, :, :, variable_idx1] = \
                            np.load(self.variable_paths[hemisphere]['circday'].format(
                                'cos',
                                forecast_start_date.month,
                                forecast_start_date.day))
                        X[sample_idx, :, :, variable_idx1 + 1] = \
                            np.load(self.variable_paths[hemisphere]['circday'].format(
                                'sin',
                                forecast_start_date.month,
                                forecast_start_date.day))

                    variable_idx1 += self.num_input_channels_dict[varname]

        return X, y

    def __getitem__(self, batch_idx):
        '''
        Generate one batch of data of size `batch_size` at batch index `batch_idx`
        into the set of batches in the epoch.
        '''

        batch_start = batch_idx * self.config['batch_size']
        batch_end = np.min([(batch_idx + 1) * self.config['batch_size'], len(self.all_forecast_IDs)])

        sample_idxs = np.arange(batch_start, batch_end)
        batch_IDs = [self.all_forecast_IDs[sample_idx] for sample_idx in sample_idxs]

        return self.data_generation(batch_IDs)

    def __len__(self):
        ''' Returns the number of batches per training epoch. '''
        return int(np.ceil(len(self.all_forecast_IDs) / self.config['batch_size']))

    def on_epoch_end(self):
        """ Randomly shuffles training samples after each epoch. """

        if self.config['verbose_level'] >= 2:
            print("on_epoch_end called")

        # Randomly shuffle the forecast IDs in-place
        self.rng.shuffle(self.all_forecast_IDs)

    def time_batch_generation(self, num_batches):
        """ Print the time taken to generate `num_batches` batches """
        tot_dur = 0
        tic_batch_gen = time.time()
        for batch_idx in range(num_batches):
            X, y = self.__getitem__(batch_idx)
        tot_dur = time.time() - tic_batch_gen

        dur_per_batch = 1000 * tot_dur / num_batches  # in ms
        dur_per_epoch = dur_per_batch * len(self) / 1000  # in seconds
        dur_per_epoch_min = np.floor(dur_per_epoch / 60)
        dur_per_epoch_sec = dur_per_epoch % 60

        print("Duration: {:.2f}s for {} batches, {:.2f}ms per batch, {:.0f}m:{:.0f}s per epoch".
              format(tot_dur, num_batches, dur_per_batch, dur_per_epoch_min, dur_per_epoch_sec))


###############################################################################
############### LEARNING RATE SCHEDULER
###############################################################################


def make_exp_decay_lr_schedule(rate, start_epoch=1, end_epoch=np.inf):

    ''' Returns an exponential learning rate function that multiplies by
    exp(-rate) each epoch after `start_epoch`. '''

    def lr_scheduler_exp_decay(epoch, lr, verbose=True):
        ''' Learning rate scheduler for fine tuning.
        Exponential decrease after start_epoch until end_epoch. '''

        if epoch >= start_epoch and epoch < end_epoch:
            lr = lr * np.math.exp(-rate)

        if verbose:
            print('\nSetting learning rate to: {}\n'.format(lr))

        return lr

    return lr_scheduler_exp_decay


###############################################################################
############### ERA5
###############################################################################


def assignLatLonCoordSystem(cube):
    ''' Assign coordinate system to iris cube to allow regridding. '''

    cube.coord('latitude').coord_system = iris.coord_systems.GeogCS(6367470.0)
    cube.coord('longitude').coord_system = iris.coord_systems.GeogCS(6367470.0)

    return cube


def fix_near_real_time_era5_coords(da):

    '''
    ERA5 data within several months of the present date is considered as a
    separate system, ERA5T. Downloads that contain both ERA5 and ERA5T data
    produce datasets with a length-2 'expver' dimension along axis 1, taking a value
    of 1 for ERA5 and a value of 5 for ERA5. This results in all-NaN values
    along latitude & longitude outside of the valid expver time span. This function
    finds the ERA5 and ERA5T time indexes and removes the expver dimension
    by concatenating the sub-arrays where the data is not NaN.
    '''

    if 'expver' in da.coords:
        # Find invalid time indexes in expver == 1 (ERA5) dataset
        arr = da.sel(expver=1).data
        arr = arr.reshape(arr.shape[0], -1)
        arr = np.sort(arr, axis=1)
        era5t_time_idxs = (arr[:, 1:] != arr[:, :-1]).sum(axis=1)+1 == 1
        era5t_time_idxs = (era5t_time_idxs) | (np.isnan(arr[:, 0]))

        era5_time_idxs = ~era5t_time_idxs

        da = xr.concat((da[era5_time_idxs, 0, :], da[era5t_time_idxs, 1, :]), dim='time')

        da = da.reset_coords('expver', drop=True)

        return da

    else:
        raise ValueError("'expver' not found in dataset.")


###############################################################################
############### ERA5 WIND VECTOR ROTATION
###############################################################################


def gridcell_angles_from_dim_coords(cube):
    """
    Author: Tony Phillips (BAS)

    Wrapper for :func:`~iris.analysis.cartography.gridcell_angles`
    that derives the 2D X and Y lon/lat coordinates from 1D X and Y
    coordinates identifiable as 'x' and 'y' axes

    The provided cube must have a coordinate system so that its
    X and Y coordinate bounds (which are derived if necessary)
    can be converted to lons and lats
    """

    # get the X and Y dimension coordinates for the cube
    x_coord = cube.coord(axis='x', dim_coords=True)
    y_coord = cube.coord(axis='y', dim_coords=True)

    # add bounds if necessary
    if not x_coord.has_bounds():
        x_coord = x_coord.copy()
        x_coord.guess_bounds()
    if not y_coord.has_bounds():
        y_coord = y_coord.copy()
        y_coord.guess_bounds()

    # get the grid cell bounds
    x_bounds = x_coord.bounds
    y_bounds = y_coord.bounds
    nx = x_bounds.shape[0]
    ny = y_bounds.shape[0]

    # make arrays to hold the ordered X and Y bound coordinates
    x = np.zeros((ny, nx, 4))
    y = np.zeros((ny, nx, 4))

    # iterate over the bounds (in order BL, BR, TL, TR), mesh them and
    # put them into the X and Y bound coordinates (in order BL, BR, TR, TL)
    c = [0, 1, 3, 2]
    cind = 0
    for yi in [0, 1]:
        for xi in [0, 1]:
            xy = np.meshgrid(x_bounds[:, xi], y_bounds[:, yi])
            x[:,:,c[cind]] = xy[0]
            y[:,:,c[cind]] = xy[1]
            cind += 1

    # convert the X and Y coordinates to longitudes and latitudes
    source_crs = cube.coord_system().as_cartopy_crs()
    target_crs = ccrs.PlateCarree()
    pts = target_crs.transform_points(source_crs, x.flatten(), y.flatten())
    lons = pts[:, 0].reshape(x.shape)
    lats = pts[:, 1].reshape(x.shape)

    # get the angles
    angles = iris.analysis.cartography.gridcell_angles(lons, lats)

    # add the X and Y dimension coordinates from the cube to the angles cube
    angles.add_dim_coord(y_coord, 0)
    angles.add_dim_coord(x_coord, 1)

    # if the cube's X dimension preceeds its Y dimension
    # transpose the angles to match
    if cube.coord_dims(x_coord)[0] < cube.coord_dims(y_coord)[0]:
        angles.transpose()

    return angles


def invert_gridcell_angles(angles):
    """
    Author: Tony Phillips (BAS)

    Negate a cube of gridcell angles in place, transforming
    gridcell_angle_from_true_east <--> true_east_from_gridcell_angle
    """
    angles.data *= -1

    names = ['true_east_from_gridcell_angle', 'gridcell_angle_from_true_east']
    name = angles.name()
    if name in names:
        angles.rename(names[1 - names.index(name)])


def rotate_grid_vectors(u_cube, v_cube, angles):
    """
    Author: Tony Phillips (BAS)

    Wrapper for :func:`~iris.analysis.cartography.rotate_grid_vectors`
    that can rotate multiple masked spatial fields in one go by iterating
    over the horizontal spatial axes in slices
    """
    # lists to hold slices of rotated vectors
    u_r_all = iris.cube.CubeList()
    v_r_all = iris.cube.CubeList()

    # get the X and Y dimension coordinates for each source cube
    u_xy_coords = [u_cube.coord(axis='x', dim_coords=True),
                   u_cube.coord(axis='y', dim_coords=True)]
    v_xy_coords = [v_cube.coord(axis='x', dim_coords=True),
                   v_cube.coord(axis='y', dim_coords=True)]

    # iterate over X, Y slices of the source cubes, rotating each in turn
    for u, v in zip(u_cube.slices(u_xy_coords, ordered=False),
                    v_cube.slices(v_xy_coords, ordered=False)):
        u_r, v_r = iris.analysis.cartography.rotate_grid_vectors(u, v, angles)
        u_r_all.append(u_r)
        v_r_all.append(v_r)

    # return the slices, merged back together into a pair of cubes
    return (u_r_all.merge_cube(), v_r_all.merge_cube())
