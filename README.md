# Hokkaido Soil project

## instiliation guide
### clone GIT repo
git clone https://github.com/HirotoBauer/hokkaido_soil

### set up environment
cd into the project directory and run the following commands:
micromamba create -p "$PWD/.micromamba" -f environment.yml
micromamba activate hokkaido_soil_moisture
pip install -e .

the contents of the data folder can be obtained from iide kaiganJ/hiroto/hokkaido_soil/data


## notes on the dataset
### 1 km soil moisture dataset
Band 1: 6 am pass data
Band 2: 6 pm pass data

### 400 m soil moisture dataset
Band 1:
Band 2: 
Revisit time of 1-2 days