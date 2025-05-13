# -*- coding: utf-8 -*-
'''
Module containing various math utilities.

Created on 12 March 2025
@author: Tim Moerkerken
Copyright © 2025 Tim Moerkerken, Delmic

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
version 2 as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see http://www.gnu.org/licenses/.
'''


import statistics
from typing import Iterable, List, Optional, Tuple


def argmin(iterable: Iterable[float]) -> List:
    """
    Returns the indices of the elements in the iterable sorted based on their values.

    :param iterable: An iterable of float values.
    :return: A list of indices sorted based on the values in the iterable.
    """
    iterable = list(iterable)
    return sorted(range(len(iterable)), key=lambda i: iterable[i])


def covariance(x: Iterable[float], y: Iterable[float]) -> float:
    """
    Calculates covariance, a measure of the joint variability, between two datasets.
    TODO: An identical function is introduced in Python 3.10 as part of the statistics library. Remove this function and
    replace its uses by statistics.covariance once the Python version is upgraded.

    :param x: Dataset x fo size n
    :param y: Dataset y of size n
    :return: Covariance between x and y
    """
    if len(x) != len(y):
        raise ValueError("Both lists must have the same length.")
    if len(x) < 2:
        raise ValueError("At least two data points are required.")

    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y)) / (len(x) - 1)
    return cov


def linear_regression(regression_points: List[tuple], slope: Optional[bool] = None) -> Tuple[float]:
    """
    Performs linear regression on a set of points.

    :param regression_points: A list of (x, y) points to perform regression on.
    :param slope: The slope of the line. If not provided, it will be calculated.
    :return: the linear regression coefficients (slope, intercept)
    """

    x_values, y_values = zip(*regression_points)
    mean_x = statistics.mean(x_values)
    mean_y = statistics.mean(y_values)

    if not slope:
        # Compute slope (a) if not provided
        slope = covariance(x_values, y_values) / statistics.variance(x_values)

    # Compute intercept (b)
    intercept = mean_y - slope * mean_x

    return slope, intercept
