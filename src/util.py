# -*- coding: utf-8 -*-
'''
Created on 8 October 2019
@author: Anders Muskens
Copyright © 2019 Anders Muskens, Delmic

This module contains several util functions for wx Python GUI calls
'''

import queue
from decorator import decorator
from functools import wraps
import inspect
import logging
import threading
import time
import weakref
import wx

@decorator
def call_in_wx_main(f, self, *args, **kwargs):
    """ This method decorator makes sure the method is called from the main
    (GUI) thread.
    The function will run asynchronously, so the function return value cannot
    be returned. So it's typically an error if a decorated function returns
    something useful.
    """
    # We could try to be clever, and only run asynchronously if it's not called
    # from the main thread, but that can cause anachronic issues. For example:
    # 1. Call from another thread -> queued for later
    # 2. Call from main thread -> immediately executed
    # => Call 2 is executed before call 1, which could mean that an old value
    # is displayed on the GUI.
    # TODO: with Python 3, update that line to:
    # if threading.current_thread() == threading.main_thread()
#     if isinstance(threading.current_thread(), threading._MainThread):
#         f(self, *args, **kwargs)
#         return

    wx.CallAfter(f, self, *args, **kwargs)

def _li_thread(delay, q):

    try:
        exect = time.time()
        while True:
            # read the latest arguments in the queue (if there are more)
            t, f, args, kwargs = q.get() # first wait until there is something
            if t is None:
                return

            # wait until it's time for it
            next_t = (min(exect, t) + delay)
            while True: # discard arguments if there is newer calls already queued
                sleep_t = next_t - time.time()
                if sleep_t > 0:
                    # logging.debug("waiting %f s until executing call", sleep_t)
                    # time.sleep(sleep_t)
                    timeout = sleep_t
                    block = True
                else: # just check one last time
                    block = False
                    timeout = None

                try:
                    t, f, args, kwargs = q.get(block=block, timeout=timeout)
                    if t is None: # Sign that we should stop (object is gone)
                        return
                    # logging.debug("Overriding call with call at %f", t)
                except queue.Empty:
                    break

            try:
                exect = time.time()
                # logging.debug("executing function %s with a delay of %f s", f.__name__, exect - t)
                f(*args, **kwargs)
            except Exception:
                logging.exception("During limited invocation call")

            # clean up early, to avoid possible cyclic dep on the instance
            del f, args, kwargs

    finally:
        logging.debug("Ending li thread")

def limit_invocation(delay_s):
    """ This decorator limits how often a method will be executed.
    The first call will always immediately be executed. The last call will be
    delayed 'delay_s' seconds at the most. In between the first and last calls,
    the method will be executed at 'delay_s' intervals. In other words, it's
    a rate limiter.
    :param delay_s: (float) The minimum interval between executions in seconds.
    Note that the method might be called in a separate thread. In wxPython, you
    might need to decorate it by @call_in_wx_main to ensure it is called in the GUI
    thread.
    """

    if delay_s > 5:
        logging.warn("Warning! Long delay interval. Please consider using "
                     "an interval of 5 or less seconds")

    def li_dec(f):
        # Share a lock on the class (as it's not easy on the instance)
        # Note: we can only do this at init, after it's impossible to add/set
        # attribute on an method
        f._li_lock = threading.Lock()

        # Hacky way to store value per instance and per methods
        last_call_name = '%s_lim_inv_last_call' % f.__name__
        queue_name = '%s_lim_inv_queue' % f.__name__
        wr_name = '%s_lim_inv_wr' % f.__name__

        @wraps(f)
        def limit(self, *args, **kwargs):
            if inspect.isclass(self):
                raise ValueError("limit_invocation decorators should only be "
                                 "assigned to instance methods!")

            now = time.time()
            with f._li_lock:
                # If the function was called later than 'delay_s' seconds ago...
                if (hasattr(self, last_call_name) and
                    now - getattr(self, last_call_name) < delay_s):
                    # logging.debug('Delaying method call')
                    try:
                        q = getattr(self, queue_name)
                    except AttributeError:
                        # Create everything need
                        q = queue.Queue()
                        setattr(self, queue_name, q)

                        # Detect when instance of self is dereferenced
                        # and kill thread then
                        def on_deref(obj):
                            # logging.debug("object %r gone", obj)
                            q.put((None, None, None, None)) # ask the thread to stop

                        wref = weakref.ref(self, on_deref)
                        setattr(self, wr_name, wref)

                        t = threading.Thread(target=_li_thread,
                                             name="li thread for %s" % f.__name__,
                                             args=(delay_s, q))
                        t.daemon = True
                        t.start()

                    q.put((now, f, (self,) + args, kwargs))
                    setattr(self, last_call_name, now + delay_s)
                    return
                else:
                    # execute method call now
                    setattr(self, last_call_name, now)

            return f(self, *args, **kwargs)
        return limit
    return li_dec

def call_in_wx_main_wrapper(f):

    @wraps(f)
    def call_after_wrapzor(*args, **kwargs):
        try:
            wx.CallAfter(f, *args, **kwargs)
        except AssertionError:
            if not wx.GetApp():
                logging.info("Skipping call to %s() as wxApp is already ended", f.__name__)
            else:
                raise

    return call_after_wrapzor

def dead_object_wrapper(f):

    @wraps(f)
    def dead_object_wrapzor(*args, **kwargs):
        if not wx.GetApp():
            logging.info("Skipping call to %s() as wxApp is already ended", f.__name__)
            return

        try:
            return f(*args, **kwargs)
        except RuntimeError:
            logging.warning("Dead object ignored in %s", f.__name__)

    return dead_object_wrapzor

def wxlimit_invocation(delay_s):
    """ This decorator limits how often a method will be executed.
    Same as util.limit_invocation, but also avoid problems with wxPython dead
    objects that can happen due to delaying a calling a method, and ensure it
    runs in the main GUI thread.
    The first call will always immediately be executed. The last call will be
    delayed 'delay_s' seconds at the most. In between the first and last calls,
    the method will be executed at 'delay_s' intervals. In other words, it's
    a rate limiter.
    :param delay_s: (float) The minimum interval between executions in seconds.
    Note that the method is _always_ called within the main GUI thread, and
    with dead object protection, so there is no need to also decorate it with
    @call_in_wx_main or @ignore_dead.
    """
    liwrapper = limit_invocation(delay_s)

    def wxwrapper(f):
        # The order matters: dead protection must happen _after_ the call has
        # been delayed
        wf = dead_object_wrapper(f)
        wf = call_in_wx_main_wrapper(wf)
        return liwrapper(wf)
    return wxwrapper