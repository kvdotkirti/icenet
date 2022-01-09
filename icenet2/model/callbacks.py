import sys
import os
import numpy as np
import tensorflow as tf

from dateutil import relativedelta

import matplotlib.pyplot as plt
import pandas as pd


class IceNetPreTrainingEvaluator(tf.keras.callbacks.Callback):
    """
    Custom tf.keras callback to update the `logs` dict used by all other callbacks
    with the validation set metrics. The callback is executed every
    `validation_frequency` batches.

    This can be used in conjuction with the BatchwiseModelCheckpoint callback to
    perform a model checkpoint based on validation data every N batches - ensure
    the `save_frequency` input to BatchwiseModelCheckpoint is also set to
    `validation_frequency`.

    Also ensure that the callbacks list past to Model.fit() contains this
    callback before any other callbacks that need the validation metrics.

    Also use Weights and Biases to log the training and validation metrics.
    """

    def __init__(self, validation_frequency, val_dataloader, sample_at_zero=False):
        self.validation_frequency = validation_frequency
        self.val_dataloader = val_dataloader
        self.sample_at_zero = sample_at_zero

    def on_train_batch_end(self, batch, logs=None):

        if (batch == 0 and self.sample_at_zero) or (batch + 1) % self.validation_frequency == 0:
            val_logs = self.model.evaluate(self.val_dataloader, verbose=0, return_dict=True)
            val_logs = {'val_' + name: val for name, val in val_logs.items()}
            logs.update(val_logs)
            [print('\n' + k + ' {:.2f}'.format(v)) for k, v in logs.items()]
            print('\n')


class BatchwiseModelCheckpoint(tf.keras.callbacks.Callback):
    """
    Docstring TODO
    """

    def __init__(self, save_frequency, model_path, mode, monitor, prev_best=None, sample_at_zero=False):
        self.save_frequency = save_frequency
        self.model_path = model_path
        self.mode = mode
        self.monitor = monitor
        self.sample_at_zero = sample_at_zero

        if prev_best is not None:
            self.best = prev_best

        else:
            if self.mode == 'max':
                self.best = -np.Inf
            elif self.mode == 'min':
                self.best = np.Inf

    def on_train_batch_end(self, batch, logs=None):

        if (batch == 0 and self.sample_at_zero) or (batch + 1) % self.save_frequency == 0:
            if self.mode == 'max' and logs[self.monitor] > self.best:
                save = True

            elif self.mode == 'min' and logs[self.monitor] < self.best:
                save = True

            else:
                save = False

            if save:
                print('\n{} improved from {:.3f} to {:.3f}. Saving model to {}.\n'.
                      format(self.monitor, self.best, logs[self.monitor], self.model_path))

                self.best = logs[self.monitor]

                self.model.save(self.model_path, overwrite=True)
            else:
                print('\n{}={:.3f} did not improve from {:.3f}\n'.format(self.monitor, logs[self.monitor], self.best))
