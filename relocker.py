# -*- coding: utf-8 -*-
"""
Created on Mon Feb  8 11:20:59 2021

@author: Dan
"""

import sys
import time
import json
import csv
import math
from pathlib import Path
from pyrpl import Pyrpl
from qtpy import QtCore, QtWidgets, QtGui
from functools import partial
import pyqtgraph as pg

class QHLine(QtGui.QFrame):
    "Horizontal line class used in the GUI"
    def __init__(self):
        super(QHLine, self).__init__()
        self.setFrameShape(QtGui.QFrame.HLine)
        self.setFrameShadow(QtGui.QFrame.Sunken)
        
class QVLine(QtGui.QFrame):
    "Vertical line class used in the GUI"
    def __init__(self):
        super(QVLine, self).__init__()
        self.setFrameShape(QtGui.QFrame.VLine)
        self.setFrameShadow(QtGui.QFrame.Sunken)

class counter_thread(QtCore.QThread):
    """External counter object to prevent GUI freezing before counter has 
    reached max. value.
    """
    _signal = QtCore.Signal(int)
    def __init__(self,refresh_time=10):
        super(counter_thread, self).__init__()
        self.refresh_time = refresh_time

    def __del__(self):
        self.wait()

    def run(self):
        for i in range(101):
            time.sleep(self.refresh_time/101)
            self._signal.emit(i)

class rp_lockbox():
    """Wrapper class to make PyRPL functions easily accessible"""
    
    def __init__(self,hostname,config='relocker',gui=False):
        self.p = Pyrpl(hostname=hostname,config=config,gui=gui)#,modules=[])
        self.p.hide_gui()
        self.rp = self.p.rp
    
    def hide_gui(self):
        self.p.hide_gui()
    
    def show_gui(self):
        self.p.show_gui()
    
    def get_pid_object(self,laser_index):
        if laser_index == 0:
            pid = self.rp.pid0
        elif laser_index == 1:
            pid = self.rp.pid1
        elif laser_index == 2:
            pid = self.rp.pid2
        else:
            print("RP does not support pid > 2")
        return pid
    
    def get_asg_object(self,laser_index):
        if laser_index == 0:
            asg = self.rp.asg0
        elif laser_index == 1:
            asg = self.rp.asg1
        else:
            print("RP does not support asg > 1")
        return asg   

    
class lockbox_gui(QtWidgets.QMainWindow):
    """Main lockbox GUI class containing the different laser controls."""
    
    def __init__(self,lasers):
        super().__init__()

        # Set some main window's properties
        self.setWindowTitle('RedPitaya AutoRelocker')
        self.resize(350, 950)
        # Set the central widget and the general layout
        self.main_layout = QtWidgets.QVBoxLayout()
        self._centralWidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self._centralWidget)
        self._centralWidget.setLayout(self.main_layout)
        self._create_header()
        self.main_layout.addWidget(QHLine())
        self.lasers_layout = QtWidgets.QHBoxLayout()
        self.main_layout.addLayout(self.lasers_layout)
        self.lasers = {}
        index = 0
        self.lasers_layout.addWidget(QVLine())
        for laser in lasers:
            self.lasers[laser] = laser_controls(self,name=laser,index=index)
            self.lasers_layout.addWidget(QVLine())
            index += 1
        self.main_layout.addWidget(QHLine())
    
    def _create_header(self):
        """Creates overall header for the main gui."""
        header_layout = QtWidgets.QGridLayout()
        # pyrpl_gui_label = QtWidgets.QLabel("PyRPL GUI")
        self.pyrpl_gui_button = QtWidgets.QPushButton("PyRPL GUI")
        self.pyrpl_gui_button.setCheckable(True)
        # header_layout.addWidget(pyrpl_gui_label,0,0,1,3)
        header_layout.addWidget(self.pyrpl_gui_button,0,0)
        self.main_layout.addLayout(header_layout)
        

class laser_controls(QtWidgets.QMainWindow):
    """Seperate control widget for each laser."""
    
    def __init__(self,lockbox_gui,name,index):
        super().__init__()
        self.name = name
        self.index = index
        self.has_updated = False
        self.is_locked = False
        self.last_locked_time = None
        self.is_relocking = False
        self.has_relocked = False
        self.pid_controls_unlocked = False
        self.pid_enabled = False
        self.sweep_enabled = False
        self.relock_voltage = 0.5
        self.inittime = time.localtime()
        self._populate_parameters()
        self._create_log_dir()
        self.laser_layout = QtWidgets.QVBoxLayout()
        self._create_header()
        self._create_refresh_apply_buttons()
        self._create_inputoutput()
        self._create_horizontal_line()
        self._create_pid_control()
        self._create_horizontal_line()
        self._create_scope_graph()
        self._create_autoupdate_control()
        self._create_locking_status()
        self._create_autorelock_control()
        self._create_horizontal_line()
        self._create_additional_options()
        self._create_horizontal_line()
        self._create_sweep_controls()
        lockbox_gui.lasers_layout.addLayout(self.laser_layout)
        self._set_enabled(False)
        
    def _populate_parameters(self):
        """Loads a name.json file with the laser parameters from the wdir. If 
        this file doesn't exist then the default parameters are loaded. Will
        always default to having input/output off.
        """
        try:
            with open(self.name+'.json','r') as f:
                self.parameters = json.load(f)
        except:
            self.parameters = {}
        defaults = {
            "input": "off",
            "output": "off",
            "P": 0,
            "I [Hz]": 0,
            "setpoint [V]": 0,
            "integrator": 0,
            "autoupdate interval [s]": 10,
            "relock interval [s]": 1,
            "scope duration [s]": 1,
            "max voltage [V]": 1,
            "min voltage [V]": 0,
            "relock voltage [V]": 0.5,
            "relock setting": "centre",
            "sweep max [V]": 1,
            "sweep min [V]": 0,
            "sweep frequency [Hz]": 50
            }
        self.parameters = {**defaults, **self.parameters}
        self.parameters["input"] = "off"
        self.parameters["output"] = "off"
        if self.parameters["relock setting"] == "prev":
            self.parameters["relock setting"] = "centre"
        with open(self.name+'.json','w') as f:
            json.dump(self.parameters, f, sort_keys=True, indent=4)
    
    def _create_log_dir(self):
        """Creates a log directory used for saving the lockbox state if it 
        doesn't already exist."""
        self.log_dir = Path.cwd()/Path("logs/"+self.name+
                                       time.strftime("/%Y/%m/%d",time.localtime()))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.log_dir/(time.strftime("%H%M%S",self.inittime)+'.csv')
    
    def _create_header(self):
        header_layout = QtWidgets.QGridLayout()
        laser_label = QtWidgets.QLabel("<h1>"+self.name+"</h1>")
        self.enable_button = QtWidgets.QPushButton("enable")
        self.enable_button.setCheckable(True)
        header_layout.addWidget(laser_label,0,0,1,3)
        header_layout.addWidget(self.enable_button,0,3)
        self.laser_layout.addLayout(header_layout)
        
    def _create_inputoutput(self):
        layout = QtWidgets.QGridLayout()
        self.input_box = QtWidgets.QComboBox()
        self.input_box.addItems(["off","in1","in2"])
        input_label = QtWidgets.QLabel("Input:")
        input_label.setStyleSheet("color: #1f77b4")
        self.output_box = QtWidgets.QComboBox()
        self.output_box.addItems(["off","out1","out2"])
        output_label = QtWidgets.QLabel("Output:")
        output_label.setStyleSheet("color: #ff7f0e")
        layout.addWidget(input_label,0,0,1,1)
        layout.addWidget(self.input_box,0,1,1,3)
        layout.addWidget(output_label,1,0,1,1)
        layout.addWidget(self.output_box,1,1,1,3)
        self.laser_layout.addLayout(layout)

    def _create_pid_control(self):
        layout = QtWidgets.QGridLayout()
        pid_label = QtWidgets.QLabel("<h2>PI control</h2>")
        self.pid_button = QtWidgets.QPushButton("enable PI")
        self.pid_button.setCheckable(True)        
        self.pid_controls_button = QtWidgets.QPushButton("unlock controls")
        self.pid_controls_button.setCheckable(True)
        p_label = QtWidgets.QLabel("P:")
        i_label = QtWidgets.QLabel("I (unity-gain frequency) [Hz]:")
        setpoint_label = QtWidgets.QLabel("setpoint [V]:")
        integrator_label = QtWidgets.QLabel("integrator:")
        self.p_box = QtWidgets.QLineEdit()
        self.p_box.setValidator(QtGui.QDoubleValidator())
        self.i_box = QtWidgets.QLineEdit()
        self.i_box.setValidator(QtGui.QDoubleValidator())
        self.setpoint_box = QtWidgets.QLineEdit()
        self.setpoint_box.setValidator(QtGui.QDoubleValidator())
        self.integrator_box = QtWidgets.QLineEdit()
        self.integrator_box.setValidator(QtGui.QDoubleValidator())
        self.integrator_reset_button = QtWidgets.QPushButton("reset")
        layout.addWidget(pid_label,0,0,1,2)
        layout.addWidget(self.pid_controls_button,0,2,1,1)
        layout.addWidget(self.pid_button,0,3,1,1)
        layout.addWidget(p_label,1,0,1,1)
        layout.addWidget(self.p_box,1,1,1,3)
        layout.addWidget(i_label,2,0,1,1)
        layout.addWidget(self.i_box,2,1,1,3)
        layout.addWidget(setpoint_label,3,0,1,1)
        layout.addWidget(self.setpoint_box,3,1,1,3)
        layout.addWidget(integrator_label,4,0,1,1)
        layout.addWidget(self.integrator_box,4,1,1,2)
        layout.addWidget(self.integrator_reset_button,4,3,1,1)
        self.pid_widgets = [self.p_box,self.i_box,self.setpoint_box,
                            self.integrator_box,self.integrator_reset_button]
        self.laser_layout.addLayout(layout)
        
    def _create_refresh_apply_buttons(self):
        layout = QtWidgets.QHBoxLayout()
        self.refresh_button = QtWidgets.QPushButton("refresh")
        self.apply_button = QtWidgets.QPushButton("apply")
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.apply_button)
        self.laser_layout.addLayout(layout)
        
    def _create_scope_graph(self):
        layout = QtWidgets.QVBoxLayout()
        self.time_label = QtWidgets.QLabel("")
        # self.graph_canvas = MplCanvas(self, width=4, height=2)#, dpi=100)
        # self.graph_canvas.axes.set_xlabel('time [s]')
        # self.graph_canvas.axes.plot(0,0)
        self.update_graph_button = QtWidgets.QPushButton("update")
        
        self.scope_plot = pg.plot(labels={'left': ('signal','V'), 'bottom': ('time','s')})
        self.scope_plot.setBackground(None)
        self.scope_plot.getAxis('left').setTextPen('k')
        self.scope_plot.getAxis('bottom').setTextPen('k')
        self.scope_plot.setRange(yRange=[-1,1])
        # y1 = [5, 5, 7, 10, 3, 8, 9, 1, 6, 2]
        # x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # bargraph = pg.BarGraphItem(x = x, height = y1, width = 0.6, brush ='g')
        # scope_plot.addItem(bargraph)
        
        layout.addWidget(self.time_label)
        layout.addWidget(self.scope_plot)
        layout.addWidget(self.update_graph_button)
        self.laser_layout.addLayout(layout)
        
    def _create_autoupdate_control(self):
        layout = QtWidgets.QGridLayout()
        self.autoupdate_button = QtWidgets.QPushButton("autoupdate")
        self.autoupdate_button.setCheckable(True)
        self.progress_bar = QtWidgets.QProgressBar()
        layout.addWidget(self.autoupdate_button,0,0,1,1)
        layout.addWidget(self.progress_bar,0,1,1,3)
        self.laser_layout.addLayout(layout)
        
    def _create_locking_status(self):
        layout = QtWidgets.QVBoxLayout()
        self.locked_label = QtWidgets.QLabel("<h2>Locked?</h2>")
        self.locked_label.setAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        self.locked_label.setStyleSheet("background: gray")
        layout.addWidget(self.locked_label)
        self.laser_layout.addLayout(layout)
    
    def _create_autorelock_control(self):
        layout = QtWidgets.QGridLayout()
        self.relock_button = QtWidgets.QPushButton("relock")
        self.autorelock_button = QtWidgets.QPushButton("autorelock")
        self.autorelock_button.setCheckable(True)
        self.relock_bar = QtWidgets.QProgressBar()
        relock_v_label = QtWidgets.QLabel("relock voltage")
        self.centre_relock_v_button = QtWidgets.QRadioButton("centre of voltage range")
        self.prev_relock_v_button = QtWidgets.QRadioButton("value at last lock")
        self.custom_relock_v_button = QtWidgets.QRadioButton("custom [V]")
        self.custom_relock_v_box = QtWidgets.QLineEdit()
        self.custom_relock_v_box.setValidator(QtGui.QDoubleValidator())
        layout.addWidget(self.relock_button,0,0,1,4)
        layout.addWidget(self.autorelock_button,1,0,1,1)
        layout.addWidget(self.relock_bar,1,1,1,3)
        layout.addWidget(self.centre_relock_v_button,2,1,1,3)
        layout.addWidget(self.prev_relock_v_button,3,1,1,3)
        layout.addWidget(self.custom_relock_v_button,4,1,1,1)
        layout.addWidget(self.custom_relock_v_box,4,2,2,1)
        layout.addWidget(relock_v_label,2,0,3,1)
        self.laser_layout.addLayout(layout)
    
    def _create_additional_options(self):
        layout = QtWidgets.QFormLayout()
        self.autoupdate_duration_box = QtWidgets.QLineEdit()
        self.autoupdate_duration_box.setValidator(QtGui.QDoubleValidator())
        self.relock_duration_box = QtWidgets.QLineEdit()
        self.relock_duration_box.setValidator(QtGui.QDoubleValidator())
        self.scope_duration_box = QtWidgets.QLineEdit()
        self.scope_duration_box.setValidator(QtGui.QDoubleValidator())
        self.max_voltage_box = QtWidgets.QLineEdit()
        self.max_voltage_box.setValidator(QtGui.QDoubleValidator())
        self.min_voltage_box = QtWidgets.QLineEdit()
        self.min_voltage_box.setValidator(QtGui.QDoubleValidator())
        layout.addRow('autoupdate interval [s]:', self.autoupdate_duration_box)
        layout.addRow('relock interval [s]:', self.relock_duration_box)
        layout.addRow('scope duration [s]:', self.scope_duration_box)
        layout.addRow('max. voltage [V]:', self.max_voltage_box)
        layout.addRow('min. voltage [V]:', self.min_voltage_box)
        self.laser_layout.addLayout(layout)
    
    def _create_sweep_controls(self):
        layout = QtWidgets.QGridLayout()
        sweep_label = QtWidgets.QLabel("<h2>sweep control</h2>")
        self.sweep_button = QtWidgets.QPushButton("enable sweep")
        self.sweep_button.setCheckable(True)
        max_label = QtWidgets.QLabel("sweep max [V]:")
        min_label = QtWidgets.QLabel("sweep min [V]:")
        freq_label = QtWidgets.QLabel("frequency [Hz]:")
        self.sweep_max_box = QtWidgets.QLineEdit()
        self.sweep_max_box.setValidator(QtGui.QDoubleValidator())
        self.sweep_min_box = QtWidgets.QLineEdit()
        self.sweep_min_box.setValidator(QtGui.QDoubleValidator())
        self.sweep_freq_box = QtWidgets.QLineEdit()
        self.sweep_freq_box.setValidator(QtGui.QDoubleValidator())
        layout.addWidget(sweep_label,0,0,1,3)
        layout.addWidget(self.sweep_button,0,3,1,1)
        layout.addWidget(max_label,1,0,1,1)
        layout.addWidget(self.sweep_max_box,1,1,1,3)
        layout.addWidget(min_label,2,0,1,1)
        layout.addWidget(self.sweep_min_box,2,1,1,3)
        layout.addWidget(freq_label,3,0,1,1)
        layout.addWidget(self.sweep_freq_box,3,1,1,3)
        self.sweep_widgets = [self.sweep_max_box,self.sweep_min_box,
                            self.sweep_freq_box]
        self.laser_layout.addLayout(layout)
          
    def _create_horizontal_line(self):
        self.laser_layout.addWidget(QHLine())
        
    def _set_enabled(self,enabled):
        """Enables/Disables controller GUI elements."""
        if not enabled:
            self.autoupdate_button.setChecked(False)
            self._set_pid_enabled(False)
            self._set_pid_control_lock(False)
            self._set_sweep_enabled(False)
        else:
            self._set_pid_enabled()
            self._set_pid_control_lock()
            self._set_sweep_enabled()
            self.locked_label.setText("<h2>Locked?</h2>")
            self.locked_label.setStyleSheet("background: gray")
        for widget in [self.input_box,self.output_box,self.refresh_button,
                        self.apply_button,self.update_graph_button,
                        self.autoupdate_button,self.scope_duration_box,
                        self.max_voltage_box,self.min_voltage_box,
                        self.autoupdate_duration_box, self.relock_button,
                        self.autorelock_button,self.relock_duration_box,
                        self.centre_relock_v_button,self.prev_relock_v_button,
                        self.custom_relock_v_button,self.pid_controls_button]:
            widget.setEnabled(enabled)

        if self.parameters['relock setting'] != 'custom':
            self.custom_relock_v_box.setEnabled(False)
        else:
            self.custom_relock_v_box.setEnabled(True)
        if self.last_locked_time == None:
            self.prev_relock_v_button.setEnabled(False)
    
    def _set_pid_enabled(self,override=None):
        if override != None:
            self.pid_button.setEnabled(override)
            self.pid_button.setChecked(override)
            # for widget in self.pid_widgets:
            #     widget.setEnabled(override)
        else:
            self.pid_button.setEnabled(True)
            self.pid_button.setChecked(self.pid_enabled)
            # for widget in self.pid_widgets:
            #     widget.setEnabled(self.pid_enabled)
    
    def _set_pid_control_lock(self,override=None):
        if override != None:
            for widget in self.pid_widgets:
                widget.setEnabled(override)
        else:
            for widget in self.pid_widgets:
                widget.setEnabled(self.pid_controls_unlocked)
    
    def _set_sweep_enabled(self,override=None):
        if override != None:
            self.sweep_button.setEnabled(override)
            self.sweep_button.setChecked(override)
            for widget in self.sweep_widgets:
                widget.setEnabled(override)
        else:
            self.sweep_button.setEnabled(True)
            self.sweep_button.setChecked(self.sweep_enabled)
            for widget in self.sweep_widgets:
                widget.setEnabled(self.sweep_enabled)
            

class lockbox_gui_ctrl():
    """Controller class for the overall lockbox GUI. Most of the functionality 
    applies to the individual laser controller objects from the GUI, referred 
    to as lc throughout.
    """
    
    def __init__(self, lockbox_gui, rp_lockbox):
        """Controller initializer."""
        self.gui = lockbox_gui
        self.lockbox = rp_lockbox
        # Connect signals and slots
        self._connectSignals()
    
    def _connectSignals(self):
        """Connect signals and slots."""
        self.gui.pyrpl_gui_button.clicked.connect(lambda:self._enable_pyrpl_gui())
        for laser in self.gui.lasers.keys():
            lc = self.gui.lasers[laser]
            lc.enable_button.clicked.connect(
                partial(self._enable_laser,lc))
            lc.input_box.activated[str].connect(
                partial(self._change_input_output,lc,'input'))
            lc.output_box.activated[str].connect(
                partial(self._change_input_output,lc,'output'))
            lc.pid_button.clicked.connect(partial(self._pid_button_ctrl,lc))
            lc.pid_controls_button.clicked.connect(partial(self._pid_controls_button_ctrl,lc))
            lc.refresh_button.clicked.connect(partial(self._refresh_params,lc))
            lc.apply_button.clicked.connect(partial(self._apply_params,lc))
            lc.update_graph_button.clicked.connect(partial(self._update_lc,lc))
            lc.autoupdate_button.clicked.connect(partial(self._enable_autoupdate,lc))
            lc.integrator_reset_button.clicked.connect(partial(self._reset_integrator,lc))
            lc.relock_button.clicked.connect(partial(self._single_relock,lc))
            lc.centre_relock_v_button.clicked.connect(partial(self._set_relock_voltage,lc,'centre'))
            lc.prev_relock_v_button.clicked.connect(partial(self._set_relock_voltage,lc,'prev'))
            lc.custom_relock_v_button.clicked.connect(partial(self._set_relock_voltage,lc,'custom'))
            lc.sweep_button.clicked.connect(partial(self._sweep_button_ctrl,lc))

    def _pid_button_ctrl(self,lc):
        if lc.pid_button.isChecked():
            lc.pid_enabled = True
            lc.sweep_enabled = False
        else:
            lc.pid_enabled = False
        lc._set_pid_enabled()
        lc._set_sweep_enabled()
        self._apply_params(lc)
        
    def _pid_controls_button_ctrl(self,lc):
        if lc.pid_controls_button.isChecked():
            lc.pid_controls_unlocked = True
        else:
            lc.pid_controls_unlocked = False
        lc._set_pid_control_lock()
        self._apply_params(lc)
        
    def _sweep_button_ctrl(self,lc):
        if lc.sweep_button.isChecked():
            lc.sweep_enabled = True
            lc.pid_enabled = False
        else:
            lc.sweep_enabled = False
        lc._set_sweep_enabled()
        lc._set_pid_enabled()
        self._apply_params(lc)

    def _enable_laser(self,lc):
        """Triggers enabling/disabling of GUI elements and enables/disables 
        relevant PyRPL parameters.
        """
        if lc.enable_button.isChecked():
            self._apply_params_from_json(lc)
            lc._set_enabled(True)
        else:
            self._refresh_params(lc)
            self._change_input_output(lc, 'input', 'off')
            self._change_input_output(lc, 'output', 'off')
            self._apply_params(lc)
            lc._set_enabled(False)
            
    def _change_input_output(self,lc,inputoutput,channel):
        """Updates input/output selection box after checking that an 
        input/output is not repeated elsewhere.
        """
        if channel != 'off':
            for other_laser in [x for x in self.gui.lasers.keys() if x != lc.name]:
                if inputoutput == 'input':
                    other_channel = self.gui.lasers[other_laser].input_box.currentText()
                else:
                    other_channel = self.gui.lasers[other_laser].output_box.currentText()
                if channel == other_channel:
                    if inputoutput == 'input':
                        lc.input_box.setCurrentText('off')
                    else:
                        lc.output_box.setCurrentText('off')
                    print('{} is already set to {} {}, so {} cannot'
                          ' also be set to {}'.format(other_laser,inputoutput,
                                                      channel,lc.name,channel))
                    channel = 'off'
        else:
            if inputoutput == 'input':
                lc.input_box.setCurrentText('off')
            else:
                lc.output_box.setCurrentText('off')
                    
    def _enable_pyrpl_gui(self):
        """Toggles the PyRPL GUI on/off."""
        if self.gui.pyrpl_gui_button.isChecked():
            self.lockbox.show_gui()
        else:
            self.lockbox.hide_gui()
        
    def _refresh_params(self,lc):
        """Gets parameters from PyRPL and saves them to name.json file
        before repopulating the GUI with them.
        """
        max_voltage,min_voltage,relock_voltage = self._get_voltage_limits(lc)
        
        pid = self.lockbox.get_pid_object(lc.index)
        asg = self.lockbox.get_asg_object(lc.index)
        lc.parameters['input'] = pid.input
        lc.parameters['output'] = asg.output_direct
        lc.parameters['P'] = pid.p
        lc.parameters['I [Hz]'] = pid.i
        lc.parameters['setpoint [V]'] = pid.setpoint
        lc.parameters['integrator'] = pid.ival
        lc.parameters['scope duration [s]'] = self.lockbox.rp.scope.duration
        lc.parameters['max voltage [V]'] = max_voltage
        lc.parameters['min voltage [V]'] = min_voltage
        lc.parameters['relock voltage [V]'] = relock_voltage
        if lc.sweep_enabled:
            lc.parameters['sweep max [V]'] = asg.offset + asg.amplitude
            lc.parameters['sweep min [V]'] = asg.offset - asg.amplitude
            lc.parameters['sweep frequency [Hz]'] = asg.frequency
        
        relock_buttons = {'centre': lc.centre_relock_v_button,
                          'prev': lc.prev_relock_v_button,
                          'custom': lc.custom_relock_v_button}
        relock_buttons[lc.parameters['relock setting']].setChecked(True)
        if lc.parameters['relock setting'] != 'custom':
            lc.custom_relock_v_box.setEnabled(False)
        else:
            lc.custom_relock_v_box.setEnabled(True)
        
        with open(lc.name+'.json','w') as f:
            json.dump(lc.parameters, f, sort_keys=True, indent=4)
        lc.input_box.setCurrentText(lc.parameters['input'])
        lc.output_box.setCurrentText(lc.parameters['output'])
        lc.p_box.setText("{:.5f}".format(lc.parameters['P']))
        lc.i_box.setText("{:.5f}".format(lc.parameters['I [Hz]']))
        lc.setpoint_box.setText("{:.5f}".format(lc.parameters['setpoint [V]']))
        lc.integrator_box.setText("{:.5f}".format(lc.parameters['integrator']))
        lc.autoupdate_duration_box.setText("{:.5f}".format(lc.parameters['autoupdate interval [s]']))
        lc.relock_duration_box.setText("{:.5f}".format(lc.parameters['relock interval [s]']))
        lc.scope_duration_box.setText("{:.5f}".format(lc.parameters['scope duration [s]']))
        lc.max_voltage_box.setText("{:.5f}".format(lc.parameters['max voltage [V]']))
        lc.min_voltage_box.setText("{:.5f}".format(lc.parameters['min voltage [V]']))
        lc.custom_relock_v_box.setText("{:.5f}".format(lc.parameters['relock voltage [V]']))
        lc.sweep_max_box.setText("{:.5f}".format(lc.parameters['sweep max [V]']))
        lc.sweep_min_box.setText("{:.5f}".format(lc.parameters['sweep min [V]']))
        lc.sweep_freq_box.setText("{:.5f}".format(lc.parameters['sweep frequency [Hz]']))
    
    def _apply_params(self,lc):
        """Gets parameters from GUI and sends them to PyRPL, refreshing 
        the parameters in case PyRPL has invoked a value limit.
        """
        pid = self.lockbox.get_pid_object(lc.index)
        pid.input = lc.input_box.currentText()
        if lc.pid_enabled:
            pid.output_direct = lc.output_box.currentText()
        else:
            pid.output_direct = 'off'
        sweep_data = [float(lc.sweep_max_box.text()),
                      float(lc.sweep_min_box.text()),
                      float(lc.sweep_freq_box.text())]
        pid.p = float(lc.p_box.text())
        pid.i = float(lc.i_box.text())
        pid.setpoint = float(lc.setpoint_box.text())
        pid.ival = float(lc.integrator_box.text())
        self._apply_autoupdate_interval(float(lc.autoupdate_duration_box.text()), lc)
        self._apply_relock_interval(float(lc.relock_duration_box.text()), lc)
        self.lockbox.rp.scope.duration = float(lc.scope_duration_box.text())
        self._apply_voltage_limits(float(lc.max_voltage_box.text()),
                                   float(lc.min_voltage_box.text()),lc,sweep_data)
        self._refresh_params(lc)
        
    def _apply_params_from_json(self,lc):
        """Gets parameters from .json and sends them to PyRPL, refreshing 
        the parameters in case PyRPL has invoked a value limit.
        """
        pid = self.lockbox.get_pid_object(lc.index)
        pid.input = lc.parameters['input']
        if lc.pid_enabled:
            pid.output_direct = lc.parameters['output']
        else:
            pid.output_direct = 'off'
        sweep_data = [lc.parameters['sweep max [V]'],
                      lc.parameters['sweep min [V]'],
                      lc.parameters['sweep frequency [Hz]']]
        pid.p = lc.parameters['P']
        pid.i = lc.parameters['I [Hz]']
        pid.setpoint = lc.parameters['setpoint [V]']
        pid.ival = lc.parameters['integrator']
        self._apply_autoupdate_interval(lc.parameters['autoupdate interval [s]'], lc)
        self._apply_relock_interval(lc.parameters['relock interval [s]'], lc)
        self.lockbox.rp.scope.duration = lc.parameters['scope duration [s]']
        self._apply_voltage_limits(lc.parameters['max voltage [V]'],
                                   lc.parameters['min voltage [V]'],lc,sweep_data)
        self._refresh_params(lc)
    
    def _apply_voltage_limits(self,max_voltage,min_voltage,lc,sweep_data=None):
        """Sets the correct voltage limits from the asg and pid modules so 
        that the pid module is a symmetric range about 0 and the asg 
        compensates so that the actual output is between the specified limits.
        Also updates and sets the relock voltage.
        """
        if max_voltage > 1:
            max_voltage = 1 
        if min_voltage < -1:
            min_voltage = -1
        if max_voltage < min_voltage:
            max_voltage = (max_voltage + min_voltage)/2
            min_voltage = max_voltage
        asg = self.lockbox.get_asg_object(lc.index)
        pid = self.lockbox.get_pid_object(lc.index)
        asg.waveform = 'dc'
        asg.amplitude = 0
        asg.frequency = 0
        if lc.parameters['relock setting'] == 'centre':
            relock_voltage = (max_voltage+min_voltage)/2
        elif lc.parameters['relock setting'] == 'prev':
            relock_voltage = self._read_relock_voltage_from_csv(lc)
            if relock_voltage == None:
                relock_voltage = (max_voltage+min_voltage)/2
        elif lc.parameters['relock setting'] == 'custom':
            try:
                relock_voltage = float(lc.custom_relock_v_box.text())
            except:
                relock_voltage = lc.parameters['relock voltage [V]']
        if relock_voltage > max_voltage:
            relock_voltage = max_voltage
        if relock_voltage < min_voltage:
            relock_voltage = min_voltage
        asg.offset = relock_voltage
        lc.parameters['max voltage [V]'] = max_voltage
        lc.parameters['min voltage [V]'] = min_voltage
        lc.parameters['relock voltage [V]'] = asg.offset
        pid.max_voltage = max_voltage - asg.offset
        pid.min_voltage = min_voltage - asg.offset
        
        if lc.sweep_enabled:
            asg.waveform = 'ramp'
            [sweep_max,sweep_min,sweep_freq] = sweep_data
            if sweep_max < sweep_min:
                sweep_max = (sweep_min+sweep_max)/2
                sweep_min = sweep_max
            if sweep_max > max_voltage:
                sweep_max = max_voltage
            if sweep_min > max_voltage:
                sweep_min = min_voltage
            if sweep_min < min_voltage:
                sweep_min = min_voltage
            if sweep_max < min_voltage:
                sweep_max = min_voltage
            asg.offset = (sweep_max+sweep_min)/2
            asg.amplitude = sweep_max - asg.offset
            asg.frequency = sweep_freq
        
        asg.trigger_source = 'immediately'
        asg.output_direct = lc.output_box.currentText()
    
    def _get_voltage_limits(self,lc):
        """Combines the asg and pid voltage limits to get the voltage limit 
        displayed in the GUI.
        """
        # # asg = lockbox.get_asg_object(lc.index)
        # pid = lockbox.get_pid_object(lc.index)
        # max_voltage = pid.max_voltage + lc.parameters['relock voltage [V]']
        # min_voltage = pid.min_voltage + lc.parameters['relock voltage [V]']
        # # relock_voltage = asg.offset
        return lc.parameters['max voltage [V]'], lc.parameters['min voltage [V]'], lc.parameters['relock voltage [V]']
    
    def _reset_integrator(self,lc):
        """Resets integrator to 0."""
        pid = self.lockbox.get_pid_object(lc.index)
        pid.ival = 0
        self._refresh_params(lc)
    
    def _update_lc(self,lc):
        """Wrapper for the various functions that occur when the update button
        is pressed or the autoupdate bar reaches 100%.
        """
        lc.has_updated = True
        self._get_scope_trace(lc)
        self._update_scope_graph(lc)
        self._update_locked_status(lc)
        self._update_locked_display(lc)
        #if lc.is_locked == True:
        self._save_lockbox_state_to_csv(lc)
        if (not lc.is_locked) and (lc.autorelock_button.isChecked()):
            self._relock(lc)
    
    def _save_lockbox_state_to_csv(self,lc):
        """Records the current time and parameters of the lockbox to a .csv, 
        including lock status and mean output voltage used for a relocking 
        event."""
        parameters = lc.parameters.copy()
        parameters['datetime'] = time.strftime("%Y%m%d%H%M%S",time.localtime())
        parameters['locked'] = lc.is_locked
        parameters['mean output voltage [V]'] = lc.mean_voltage
        csv_path = lc.csv_path
        if not lc.is_locked:
            csv_path = csv_path.with_name(csv_path.stem+'_unlocked'+csv_path.suffix)
        print(csv_path)
        try:
            with open(csv_path, 'x', newline='') as csv_file:
                w = csv.DictWriter(csv_file, parameters.keys())
                w.writeheader()
        except:
            pass
        with open(csv_path, 'a', newline='') as csv_file:
            w = csv.DictWriter(csv_file, parameters.keys())
            w.writerow(parameters)
            
    def _read_relock_voltage_from_csv(self,lc):
        try:
            with open(lc.csv_path, 'r') as csv_file:
                reader = csv.DictReader(csv_file)
                result = {}
                for row in reader:
                    for column, value in row.items():
                        result[column] = value
            return float(result['mean output voltage [V]'])
        except:
            return None
    
    def _get_scope_trace(self,lc):
        scope = self.lockbox.rp.scope
        scope.input1 = lc.parameters['input']
        scope.input2 = lc.parameters['output']
        lc.times, lc.datas = scope._get_rolling_curve()
    
    def _update_scope_graph(self,lc):
        """Gets a rolling scope trace of duration ~1 second and plots this on
        the graph in the GUI. Scope data can be used to determine if laser
        is locked or not.
        """
        if lc.last_locked_time != None:
            lc.time_label.setText("Updated at "
                              +time.strftime("%H:%M:%S",time.localtime())+", "
                              "previously locked at "
                              +time.strftime("%H:%M:%S",lc.last_locked_time))
        else:
            lc.time_label.setText("Updated at "
                              +time.strftime("%H:%M:%S",time.localtime())+", "
                              "not previously locked.")
        lc.scope_plot.clear()
        lc.scope_plot.plot(lc.times, lc.datas[0], pen=pg.mkPen(color=(31, 129, 180)))
        lc.scope_plot.plot(lc.times, lc.datas[1], pen=pg.mkPen(color=(225, 127, 14)))
    
    def _apply_autoupdate_interval(self,time,lc):
        """Updates the autoupdate timer. Handles the update regardless of 
        whether or not the counter_thread currently exists."""
        lc.parameters['autoupdate interval [s]'] = time
        try:
            lc.thread.refresh_time = time
        except:
            pass
    
    def _apply_relock_interval(self,time,lc):
        """Updates the autoupdate timer. Handles the update regardless of 
        whether or not the counter_thread currently exists."""
        lc.parameters['relock interval [s]'] = time
        try:
            lc.relock_thread.refresh_time = time
        except:
            pass
    
    def _enable_autoupdate(self,lc):
        """Controlling function for the autoupdate button. Begins the progress
        bar counting iff it does not already exist and is counting.
        """
        if lc.autoupdate_button.isChecked() and lc.progress_bar.value() <= 0:
            lc.thread = counter_thread(refresh_time=lc.parameters['autoupdate interval [s]'])
            lc.thread._signal.connect(partial(self._signal_accept,lc))
            lc.thread.start()
    
    def _signal_accept(self, lc, msg):
        """Controlling function for the progress bar. When complete, progress
        bar checks that the autoupdate button is still pressed, and iff it is
        then it updates the graph.
        """
        lc.progress_bar.setValue(int(msg))
        if lc.progress_bar.value() == 100:
            lc.progress_bar.setValue(0)
            if lc.autoupdate_button.isChecked():
                self._update_lc(lc)
                lc.thread.start()
    
    def _relock(self,lc):
        """Triggers a single relock event. Relock event will only trigger iff 
        the laser is currently not locked or relocking.
        """
        if not (lc.is_locked or lc.is_relocking):
            self._single_relock(lc)
            
    def _single_relock(self,lc):
        """Triggers a single relock event regardless of the locked status, but 
        will still not allow triggering if a relocking event is currently in 
        progress.
        """
        if not lc.has_updated:
            self._update_lc(lc)
        if not lc.is_relocking:
            lc.relock_thread = counter_thread(refresh_time=lc.parameters['relock interval [s]'])
            lc.relock_thread._signal.connect(partial(self._relock_signal_accept,lc))
            lc.relock_thread.start()
        
    def _relock_signal_accept(self, lc, msg):
        """Controlling function for the progress bar. When complete, progress
        bar checks that the autoupdate button is still pressed, and iff it is
        then it updates the graph.
        """
        lc.relock_bar.setValue(int(msg))
        if lc.relock_bar.value() == 0:
            #pid = self.lockbox.get_pid_object(lc.index)
            lc.is_relocking = True
            self._update_locked_display(lc)
            #pid.output_direct = "off"
            lc._set_pid_enabled(False)
            self._pid_button_ctrl(lc)
        elif lc.relock_bar.value() == 100:
            lc.relock_bar.setValue(0)
            #pid = self.lockbox.get_pid_object(lc.index)
            self._reset_integrator(lc)
            lc._set_pid_enabled(True)
            self._pid_button_ctrl(lc)
            #pid.output_direct = lc.parameters['output']
            lc.is_relocking = False
            lc.has_relocked = True
            self._update_locked_display(lc)
    
    def _update_locked_display(self,lc):
        if lc.is_relocking:
            lc.locked_label.setText("<h2>Relocking</h2>")
            lc.locked_label.setStyleSheet("background: yellow")
        elif lc.has_relocked:
            lc.locked_label.setText("<h2>Locked?</h2>")
            lc.locked_label.setStyleSheet("background: gray")
            lc.has_relocked = False
        elif lc.is_locked:
            lc.locked_label.setText("<h2>Locked</h2>")
            lc.locked_label.setStyleSheet("background: green")
        else:
            lc.locked_label.setText("<h2>Not locked</h2>")
            lc.locked_label.setStyleSheet("background: red")      
    
    def _update_locked_status(self,lc):
        """Attempts to determine whether the laser is locked by seeing if the 
        the mean of the output signal is within a threshold value of the 
        maximum or minimum voltage.
        """
        output = lc.datas[1]
        output = [value for value in output if not math.isnan(value)]
        #print(output)
        lc.mean_voltage = sum(output)/len(output)
        print(lc.mean_voltage)
        max_voltage = lc.parameters['max voltage [V]']
        min_voltage = lc.parameters['min voltage [V]']
        threshold = 0.01
        if ((abs(lc.mean_voltage - max_voltage) < threshold) or 
            (abs(lc.mean_voltage - min_voltage) < threshold)):
            lc.is_locked = False
        else:
            lc.is_locked = True
            lc.last_locked_time = time.localtime()
            lc.prev_relock_v_button.setEnabled(True)
            if lc.prev_relock_v_button.isChecked():
                self._apply_voltage_limits(max_voltage,min_voltage,lc)
                self._refresh_params(lc)
                
    def _set_relock_voltage(self,lc,relock_v_setting):
        lc.parameters['relock setting'] = relock_v_setting
        print(lc.parameters['relock setting'])
        self._apply_voltage_limits(lc.parameters['max voltage [V]'],
                                   lc.parameters['min voltage [V]'],lc)
        self._refresh_params(lc)
        
if __name__ == "__main__":
    def run_app():
        hostname = "129.234.190.82"
        hostname = "_FAKE_"
        lockbox = rp_lockbox(hostname,config="relocker")
        lasers = ["D1 ECDL"]
        autorelocker = QtWidgets.QApplication(sys.argv)
        view = lockbox_gui(lasers)
        view.show()
        # Create instances of the model and the controller
        lockbox_gui_ctrl(lockbox_gui=view, rp_lockbox=lockbox)
        # Execute calculator's main loop
        sys.exit(autorelocker.exec_())
    run_app()
# # Create an instance of QApplication
# if not QtWidgets.QApplication.instance():
#     autorelocker = QtWidgets.QApplication(sys.argv)
# else:
#     autorelocker = QtWidgets.QApplication.instance()
# # Show the calculator's GUI
# view = lockbox_gui(lasers)
# view.show()
# # Create instances of the model and the controller
# lockbox_gui_ctrl(lockbox_gui=view, rp_lockbox=lockbox)
# # Execute calculator's main loop
# autorelocker.exec_()