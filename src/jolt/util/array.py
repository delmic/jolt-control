# -*- coding: utf-8 -*-
'''
Module with array utilities.

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


from typing import List


def arange(vmin: float, vmax: float, step: float) -> List[float]:
    """
    Generates a list of values starting from vmin and adding steps while staying below vmax.

    :param vmin: The minimum value (inclusive).
    :param vmax: The maximum value (exclusive).
    :param step: The step size between consecutive values.
    :return: A list of values from vmin to just below vmax with the specified step.
    """
    values = []
    current = vmin
    while current < vmax:
        values.append(current)
        current += step
    return values
