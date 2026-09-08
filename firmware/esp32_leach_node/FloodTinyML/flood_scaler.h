#ifndef FLOOD_SCALER_H
#define FLOOD_SCALER_H

#include <stdint.h>

#define FLOOD_FEATURE_COUNT 10

static const float FEATURE_MIN[FLOOD_FEATURE_COUNT] = {
    /* water_level_min */,
    /* water_level_rate_min */,
    /* water_level_mean_min */,
    /* water_level_max_min */,
    /* soil_moisture_min */,
    /* soil_moisture_rate_min */,
    /* soil_moisture_mean_min */,
    /* temperature_min */,
    /* pressure_min */,
    /* pressure_change_min */
};

static const float FEATURE_MAX[FLOOD_FEATURE_COUNT] = {
    /* water_level_max */,
    /* water_level_rate_max */,
    /* water_level_mean_max */,
    /* water_level_max_max */,
    /* soil_moisture_max */,
    /* soil_moisture_rate_max */,
    /* soil_moisture_mean_max */,
    /* temperature_max */,
    /* pressure_max */,
    /* pressure_change_max */
};

#endif
