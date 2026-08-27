##### Hokkaido Soil project

## instiliation guide
# clone GIT repo
git clone https://github.com/HirotoBauer/hokkaido_soil

# set up environment
micromamba env create -f environment.yml
micromamba activate hokkaido_soil_moisture
pip install -e .

the contents of the data folder can be obtained from iide kaiganJ/hiroto/hokkaido_soil/data