# -*- coding: utf-8 -*-
'''
Module containing methods useful for measurements on the Jolt computer board.

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


import time
import logging
from typing import Callable, List, Union

logger = logging.getLogger(__name__)

# Types to be expected for generic setters and getters
GenericType = Union[str, int, float, bool]


def await_set_stabilized(
    setter: Callable[[Union[int, float]], None],
    getter: Callable[[], Union[int, float]],
    target: float,
    tolerance: float = 0,
    repeats: int = 1,
    interval: float = 0.5,
    timeout: float = 120,
) -> Union[int, float]:
    """
    Waits until the getter value stabilizes at the target value within a given tolerance.

    :param setter: A function to set the target value.
    :param getter: A function to get the current value.
    :param target: The target value to be reached.
    :param tolerance: The acceptable absolute tolerance for the target value.
    :param repeats: The number of consecutive readings within tolerance required for stabilization.
    :param interval: The interval between consecutive readings in seconds.
    :param timeout: The maximum time to wait for stabilization in seconds.
    :return: The stabilized value.
    :sideeffects: Calls the setter and getter functions repeatedly.
    """
    n_stable = 0
    setter(target)
    start_time = time.time()
    getter_name = getter.__name__
    while True:
        run_time = time.time() - start_time
        if run_time >= timeout:
            logger.debug(f"Timed out for {getter_name} to reach {target}, currently {current} within {timeout} s")
            return current
        current = getter()
        logger.debug(f"Waiting for {getter_name} to reach {target:0.3f}, currently {current:0.3f}")
        in_tolerance = abs(current - target) < tolerance
        n_stable = n_stable + 1 if in_tolerance else 0
        if n_stable >= repeats:
            return current
        time.sleep(interval)


def await_set(
    setter: Callable[[GenericType], None],
    getter: Callable[[], GenericType],
    target: GenericType,
    interval: float = 0.1,
    timeout: float = 30,
) -> GenericType:
    """
    Waits until the getter value reaches the target value or the timeout is reached.

    :param setter: A function to set the target value.
    :param getter: A function to get the current value.
    :param target: The target value to be reached.
    :param interval: The interval between consecutive readings in seconds.
    :param timeout: The maximum time to wait for the target value in seconds.
    :return: The final value after waiting.
    :sideeffects: Calls the setter and getter functions repeatedly.
    """
    setter(target)
    run_time = 0
    start_time = time.time()
    while True:
        current = getter()
        run_time = time.time() - start_time
        if current == target or run_time >= timeout:
            break
        time.sleep(interval)
    return current


def repeated_get(
    getter: Callable[[], GenericType],
    repeats: int,
    interval: float = 1,
) -> List[GenericType]:
    """
    Calls the getter function repeatedly at specified intervals and returns the results.

    :param getter: A function to get the current value.
    :param repeats: The number of times to call the getter function.
    :param interval: The interval between consecutive calls in seconds.
    :return: A list of values obtained from the getter function.
    :sideeffects: Calls the getter function repeatedly.
    """
    results = []
    getter_name = getter.__name__
    logger.debug(f"Calling {getter_name} at interval {interval} s, {repeats} repeats")
    for i in range(repeats):
        results.append(getter())
        time.sleep(interval)

    return results
