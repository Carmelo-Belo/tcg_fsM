import numpy as np
import pandas as pd
import xarray as xr
import os
from statsmodels.tsa.seasonal import STL, seasonal_decompose

def crop_field(var, lon1, lon2, lat1, lat2):
    """
    Crop the specified variable to the specified domain.

    Inputs:
        var: xarray.DataArray or xarray.Dataset
            The variable to crop
        lon1: float
            The western longitude of the domain (range: -180 to 180)
        lon2: float
            The eastern longitude of the domain (range: -180 to 180)
        lat1: float
            The southern latitude of the domain
        lat2: float
            The northern latitude of the domain
    Outputs:
        ds: xarray.DataArray or xarray.Dataset
            The cropped variable
    """
    ds = var.copy()
    # If the domain crosses/touches the meridian 180, convert to 0-360
    if (lon1 <= 180 and lon2 >= -180 and lon1 > lon2) or (lon1 == -180) or (lon2 == 180):
        ds.coords['longitude'] = (ds.longitude + 360) %360
        ds = ds.sortby(ds.longitude)
        if lon2 < 0:
            lon2 = lon2 + 360
        if lon1 < 0:
            lon1 = lon1 + 360
    return ds.sel(longitude=slice(lon1, lon2), latitude=slice(lat2, lat1))

def check_consecutive_repeats(df,col):
    repeats = df.shift(1) == df
    if repeats.sum() > 0:
        print('Consecutive values repeated found at',col)
        print(repeats[repeats].index)

def build_dataset(basin, cluster_variables, index_variables, cluster_path, indexes_path, target_path, first_year, last_year, deseasonalize, detrend, month_col=True):
    
    # Define geographical coordinates according to the basin considered
    if basin == 'NWP':
        min_lon, max_lon, min_lat, max_lat = 100, 180, 0, 40
    elif basin == 'NEP':
        min_lon, max_lon, min_lat, max_lat = -180, -75, 0, 40
    elif basin == 'NA':
        min_lon, max_lon, min_lat, max_lat = -100, 0, 0, 40
    elif basin == 'NI':
        min_lon, max_lon, min_lat, max_lat = 45, 100, 0, 40
    elif basin == 'SP':
        min_lon, max_lon, min_lat, max_lat = 135, -70, -40, 0
    elif basin == 'SI':
        min_lon, max_lon, min_lat, max_lat = 35, 135, -40, 0
    elif basin == 'GLB':
        min_lon, max_lon, min_lat, max_lat = -181, 181, -40, 40
    else:
        raise ValueError('Basin not recognized')

    # Create a dataframe containing the data for the climate indeces
    date_range = pd.date_range(start=f'{first_year}-01-01', end=f'{last_year}-12-01', freq='MS')
    df_indeces = pd.DataFrame(index=date_range, columns=index_variables)
    for climate_index in index_variables:
        filename = os.path.join(indexes_path, climate_index + '.txt')
        data = pd.read_table(filename, sep='\s+', header=None)
        for r, row in enumerate(df_indeces.iterrows()):
            idx = df_indeces.index[r]
            month = idx.month
            year = idx.year
            df_indeces.loc[idx, climate_index] = data[(data[0] == year)][month].values[0]

    # Load the cluster data and merge it in a single dataframe
    for v, var in enumerate(cluster_variables):
        filename = f'averages_{var}.csv'
        path = os.path.join(cluster_path, filename)
        if v == 0:
            dataset_cluster = pd.read_csv(path, index_col=0, parse_dates=True)
            dataset_cluster = dataset_cluster[dataset_cluster.index.isin(date_range)]
        else:
            temp = pd.read_csv(path, index_col=0, parse_dates=True)
            temp = temp[temp.index.isin(date_range)]
            dataset_cluster = pd.concat([dataset_cluster, temp], axis=1)

    # Merge the cluster and index dataframes
    dataset = pd.concat([dataset_cluster, df_indeces], axis=1)

    # Add a column containing the month of the year
    if month_col:
        dataset['month'] = dataset.index.month
    
    # Check if any data is missing, repeated in consecutive days, or is above the average+7*std
    for col in dataset.columns:
        if dataset[col].isnull().sum() > 0:
            print('Warning: Missing values in', col)
        check_consecutive_repeats(dataset[col],col)
        mean = dataset[col].mean()
        std = dataset[col].std()
        if (np.abs(dataset[col]) > mean + 7*std).sum() > 0:
            print('Warning: Values above the average+7*std in', col)

    # Build the dataframe for the target variable -> number of tropical cyclone genesis events per month
    years = np.arange(first_year, last_year+1, 1)
    tcg_ds_or = xr.concat([xr.open_dataset(target_path + f'_{year}.nc') for year in years], dim='time')
    if basin == 'NEP' or basin == 'NA':
        tcg_ds = crop_field(tcg_ds_or, min_lon, max_lon, min_lat, max_lat)
        mask = xr.open_dataarray(f'{basin}_mask.nc')
        tcg_ds = tcg_ds.where(mask == 1)
    elif basin != 'GLB':
        tcg_ds = crop_field(tcg_ds_or, min_lon, max_lon, min_lat, max_lat)
    else:
        tcg_ds = tcg_ds_or
    target = pd.DataFrame(index=date_range)
    target['tcg'] = tcg_ds.tcg.sum(dim=['latitude', 'longitude']).values.astype(int)

    # If deseasonalize is True, remove the seasonal cycle, if detrend is True, remove the trend
    if deseasonalize:
        decomposition = STL(target['tcg']).fit()
        deseason_target = target['tcg'] - decomposition.seasonal
        deseason_target = deseason_target.to_frame().rename(columns={0: 'tcg'})
        seasonal = decomposition.seasonal.to_frame()
        return dataset, target, deseason_target, seasonal
    elif detrend:
        decomposition = STL(target['tcg']).fit()
        detrend_target = target['tcg'] - decomposition.trend
        detrend_target = detrend_target.to_frame().rename(columns={0: 'tcg'})
        trend = decomposition.trend.to_frame()
        return dataset, target, detrend_target, trend
    else:
        return dataset, target
    
def build_dataset_noTS(basin, cluster_variables, index_variables, cluster_path, indexes_path, target_path, first_year, last_year, month_col=True):
    
    # Define geographical coordinates according to the basin considered
    if basin == 'NWP':
        min_lon, max_lon, min_lat, max_lat = 100, 180, 0, 40
    elif basin == 'NEP':
        min_lon, max_lon, min_lat, max_lat = -180, -75, 0, 40
    elif basin == 'NA':
        min_lon, max_lon, min_lat, max_lat = -100, 0, 0, 40
    elif basin == 'NI':
        min_lon, max_lon, min_lat, max_lat = 45, 100, 0, 40
    elif basin == 'SP':
        min_lon, max_lon, min_lat, max_lat = 135, -70, -40, 0
    elif basin == 'SI':
        min_lon, max_lon, min_lat, max_lat = 35, 135, -40, 0
    elif basin == 'GLB':
        min_lon, max_lon, min_lat, max_lat = -181, 181, -40, 40
    else:
        raise ValueError('Basin not recognized')

    # Create a dataframe containing the data for the climate indeces
    date_range = pd.date_range(start=f'{first_year}-01-01', end=f'{last_year}-12-01', freq='MS')
    df_indeces = pd.DataFrame(index=date_range, columns=index_variables)
    df_residual_indeces = pd.DataFrame(index=date_range, columns=index_variables)
    for climate_index in index_variables:
        filename = os.path.join(indexes_path, climate_index + '.txt')
        data = pd.read_table(filename, sep='\s+', header=None)
        for r, row in enumerate(df_indeces.iterrows()):
            idx = df_indeces.index[r]
            month = idx.month
            year = idx.year
            df_indeces.loc[idx, climate_index] = data[(data[0] == year)][month].values[0]
        decomp_index = STL(df_indeces[climate_index]).fit()
        df_residual_indeces[climate_index] = decomp_index.resid

    # Load the cluster data and merge it in a single dataframe
    for v, var in enumerate(cluster_variables):
        filename = f'averages_{var}.csv'
        path = os.path.join(cluster_path, filename)
        if v == 0:
            dataset_cluster = pd.read_csv(path, index_col=0, parse_dates=True)
            dataset_cluster = dataset_cluster[dataset_cluster.index.isin(date_range)]
        else:
            temp = pd.read_csv(path, index_col=0, parse_dates=True)
            temp = temp[temp.index.isin(date_range)]
            dataset_cluster = pd.concat([dataset_cluster, temp], axis=1)

    # Merge the cluster and index dataframes
    dataset = pd.concat([dataset_cluster, df_residual_indeces], axis=1)

    # Add a column containing the month of the year
    if month_col:
        dataset['month'] = dataset.index.month
    
    # Check if any data is missing, repeated in consecutive days, or is above the average+7*std
    for col in dataset.columns:
        if dataset[col].isnull().sum() > 0:
            print('Warning: Missing values in', col)
        check_consecutive_repeats(dataset[col],col)
        mean = dataset[col].mean()
        std = dataset[col].std()
        if (np.abs(dataset[col]) > mean + 7*std).sum() > 0:
            print('Warning: Values above the average+7*std in', col)

    # Build the dataframe for the target variable -> number of tropical cyclone genesis events per month
    years = np.arange(first_year, last_year+1, 1)
    tcg_ds_or = xr.concat([xr.open_dataset(target_path + f'_{year}.nc') for year in years], dim='time')
    if basin == 'NEP' or basin == 'NA':
        tcg_ds = crop_field(tcg_ds_or, min_lon, max_lon, min_lat, max_lat)
        mask = xr.open_dataarray(f'{basin}_mask.nc')
        tcg_ds = tcg_ds.where(mask == 1)
    elif basin != 'GLB':
        tcg_ds = crop_field(tcg_ds_or, min_lon, max_lon, min_lat, max_lat)
    else:
        tcg_ds = tcg_ds_or
    target = pd.DataFrame(index=date_range)
    target['tcg'] = tcg_ds.tcg.sum(dim=['latitude', 'longitude']).values.astype(int)

    # Detrend and deseasonalize the target variable
    decomposition = STL(target['tcg']).fit()
    trend = decomposition.trend.to_frame()
    seasonal = decomposition.seasonal.to_frame()
    residual = decomposition.resid.to_frame()

    return dataset, residual, trend, seasonal