"""Class for handling optimization setup, running, and saving."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy.typing as npt

import vipdopt
from vipdopt.optimization.device import Device
from vipdopt.optimization.fom import FoM
from vipdopt.optimization.optimizer import GradientOptimizer
from vipdopt.simulation import ISimulation


class Optimization:
    """Class for orchestrating all the pieces of an optimization."""

    def __init__(
            self,
            sims: list[ISimulation],
            device: Device,
            optimizer: GradientOptimizer,
            fom: FoM,
            start_epoch: int=0,
            start_iter: int=0,
            max_epochs: int=1,
            iter_per_epoch: int=100,
    ):
        """Initialize Optimzation object."""
        self.sims = sims
        self.device = device
        self.optimizer = optimizer
        self.fom = fom

        self.fom_hist: list[npt.NDArray] = []
        self.param_hist: list[npt.NDArray] = []
        self._callbacks: list[Callable[[Optimization], None]] = []

        self.epoch = start_epoch
        self.iteration = start_iter
        self.max_epochs = max_epochs
        self.iter_per_epoch = iter_per_epoch

    def add_callback(self, func: Callable):
        """Register a callback function to call after each iteration."""
        self._callbacks.append(func)

    def _simulation_dispatch(self, sim_idx: int):
        """Target for threads to run simulations."""
        sim = self.sims[sim_idx]
        vipdopt.logger.debug(f'Running simulation on thread {sim_idx}')
        sim.save(f'_sim{sim_idx}_epoch_{self.epoch}_iter_{self.iteration}')
        sim.run()
        vipdopt.logger.debug(f'Completed running on thread {sim_idx}')

    def _pre_run(self):
        """Final pre-processing before running the optimization."""
        # Connect to Lumerical
        for sim in self.sims:
            sim.connect()

    def run(self):
        """Run the optimization."""
        self._pre_run()
        while self.epoch < self.max_epochs:
            while self.iteration < self.iter_per_epoch:
                for callback in self._callbacks:
                    callback(self)

                vipdopt.logger.debug(
                    f'Epoch {self.epoch}, iter {self.iteration}: Running simulations...'
                )
                # Run all the simulations
                n_sims = len(self.sims)
                with ThreadPoolExecutor() as ex:
                    ex.map(self._simulation_dispatch, range(n_sims))

                # Compute FoM and Gradient
                fom = self.fom.compute()
                self.fom_hist.append(fom)

                gradient = self.fom.gradient()

                vipdopt.logger.debug(
                    f'FoM at epoch {self.epoch}, iter {self.iteration}: {fom}\n'
                    f'Gradient {self.epoch}, iter {self.iteration}: {gradient}'
                )

                # Step with the gradient
                self.param_hist.append(self.device.get_design_variable())
                self.optimizer.step(self.device, gradient, self.iteration)

                self.iteration += 1
            self.iteration = 0
            self.epoch += 1

        final_fom = self.fom_hist[-1]
        vipdopt.logger.info(f'Final FoM: {final_fom}')
        final_params = self.param_hist[-1]
        vipdopt.logger.info(f'Final Parameters: {final_params}')
