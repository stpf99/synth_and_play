import sys
import os
import numpy as np
from scipy import signal
from scipy.io import wavfile
import pygame
import rtmidi
import json
import random
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QSlider, QLabel, QPushButton, QRadioButton, QGroupBox, QComboBox, 
                             QGraphicsView, QGraphicsScene, QFileDialog, QLineEdit, QSpinBox, 
                             QProgressBar, QTabWidget, QScrollArea)
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPen, QPainterPath, QColor

class WavInstrumentApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WAV MIDI Instrument with Wave Generator")
        self.setMinimumSize(800, 400)

        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(128)
        
        self.sample_rate = 44100
        self.duration = 2.0
        self.t = np.linspace(0, self.duration, int(self.sample_rate * self.duration))
        
        self.base_sample = None
        self.processed_sounds = {}
        self.active_notes = {}
        
        self.wave_shapes = {
            'sine': lambda t, freq: np.sin(2 * np.pi * freq * t),
            'square': lambda t, freq: signal.square(2 * np.pi * freq * t),
            'sawtooth': lambda t, freq: signal.sawtooth(2 * np.pi * freq * t),
            'triangle': lambda t, freq: signal.sawtooth(2 * np.pi * freq * t, 0.5),
            'noise': lambda t, freq: np.random.normal(0, 1, len(t)),
            'custom': self.custom_wave  # Nowa, uproszczona wersja
        }
        
        self.params = {
            'wave_shape1': 'sine', 'wave_shape2': 'sine', 'wave_mix': 0.5, 'frequency': 440.0,
            'freq_mod': 0.0, 'freq_mod_rate': 0.0, 'amp_mod': 0.0, 'amp_mod_rate': 0.0,
            'harm1_weight': 1.0, 'harm2_weight': 0.5, 'harm3_weight': 0.25, 'harm4_weight': 0.125, 'harm5_weight': 0.0625,
            'attack_time': 0.1, 'decay_time': 0.2, 'sustain_level': 0.7, 'release_time': 0.3,
            'vibrato_rate': 0.0, 'vibrato_depth': 0.0, 'tremolo_rate': 0.0, 'tremolo_depth': 0.0,
            'distortion': 0.0, 'noise_level': 0.0, 'bit_crush': 0.0, 'fold_amount': 0.0,
            'filter_cutoff': 20000, 'filter_resonance': 0.0, 'chorus_depth': 0.0, 'chorus_rate': 0.0
        }
        
        self.presets = {}
        self.current_preset_name = ""
        self.sound = None
        self.is_looping = False
        self.play_position = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_play_position)
        self.updating_waveform = False
        self.background_timer = QTimer()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.main_tab = QWidget()
        main_layout_tab = QVBoxLayout(self.main_tab)
        self.setup_main_gui(main_layout_tab)
        self.tabs.addTab(self.main_tab, "Main")

        self.midi_tab = QWidget()
        midi_layout = QVBoxLayout(self.midi_tab)
        self.setup_midi_gui(midi_layout)
        self.tabs.addTab(self.midi_tab, "MIDI Instrument")

        self.wave_tab = QWidget()
        wave_layout = QVBoxLayout(self.wave_tab)
        self.setup_wave_gui(wave_layout)
        self.tabs.addTab(self.wave_tab, "Wave Generator")

        self.midi_in = None
        self.get_available_midi_ports()
        self.load_presets_from_directory()

    def setup_main_gui(self, layout):
        pianoroll_group = QGroupBox("Pianoroll")
        pianoroll_layout = QVBoxLayout()
        
        size_layout = QHBoxLayout()
        self.pianoroll_size_combo = QComboBox()
        self.pianoroll_size_combo.addItems(["1 Octave", "3 Octaves", "5 Octaves"])
        self.pianoroll_size_combo.currentTextChanged.connect(self.update_pianoroll)
        size_layout.addWidget(QLabel("Pianoroll Size:"))
        size_layout.addWidget(self.pianoroll_size_combo)
        pianoroll_layout.addLayout(size_layout)
        
        self.pianoroll_view = QGraphicsView()
        self.pianoroll_scene = QGraphicsScene()
        self.pianoroll_view.setScene(self.pianoroll_scene)
        self.pianoroll_view.setMinimumHeight(100)
        self.pianoroll_scene.mousePressEvent = self.pianoroll_mouse_press
        pianoroll_layout.addWidget(self.pianoroll_view)
        pianoroll_group.setLayout(pianoroll_layout)
        layout.addWidget(pianoroll_group)
        self.update_pianoroll()

        preset_group = QGroupBox("Preset Selection")
        preset_layout = QVBoxLayout()
        
        self.main_preset_combo = QComboBox()
        self.main_preset_combo.currentTextChanged.connect(self.load_main_preset)
        preset_layout.addWidget(self.main_preset_combo)
        
        self.process_preset_button = QPushButton("Process Selected Preset")
        self.process_preset_button.clicked.connect(self.process_preset)
        preset_layout.addWidget(self.process_preset_button)
        
        self.save_preset_wav_button = QPushButton("Save Preset to WAV")
        self.save_preset_wav_button.clicked.connect(self.save_preset_to_wav)
        preset_layout.addWidget(self.save_preset_wav_button)
        
        preset_group.setLayout(preset_layout)
        layout.addWidget(preset_group)

        volume_group = QGroupBox("Volume Control")
        volume_layout = QVBoxLayout()
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(self.update_volume)
        volume_layout.addWidget(QLabel("Master Volume:"))
        volume_layout.addWidget(self.volume_slider)
        
        volume_group.setLayout(volume_layout)
        layout.addWidget(volume_group)

        layout.addStretch()

    def setup_midi_gui(self, layout):
        debug_group = QGroupBox("Debug Information")
        debug_layout = QVBoxLayout()
        
        self.debug_label = QLabel("Debug info:")
        debug_layout.addWidget(self.debug_label)
        
        self.midi_debug = QLabel("MIDI status: Not connected")
        debug_layout.addWidget(self.midi_debug)
        
        self.sample_debug = QLabel("Sample status: No sample loaded")
        debug_layout.addWidget(self.sample_debug)
        
        self.note_debug = QLabel("Last MIDI event: None")
        debug_layout.addWidget(self.note_debug)
        
        debug_group.setLayout(debug_layout)
        layout.addWidget(debug_group)

        port_group = QGroupBox("MIDI Settings")
        port_layout = QVBoxLayout()
        
        self.midi_port_selector = QComboBox()
        port_layout.addWidget(QLabel("MIDI Input Port:"))
        port_layout.addWidget(self.midi_port_selector)
        
        self.refresh_ports_button = QPushButton("Refresh MIDI Ports")
        self.refresh_ports_button.clicked.connect(self.get_available_midi_ports)
        port_layout.addWidget(self.refresh_ports_button)
        
        self.connect_midi_button = QPushButton("Connect MIDI")
        self.connect_midi_button.clicked.connect(self.select_midi_input)
        port_layout.addWidget(self.connect_midi_button)
        
        port_group.setLayout(port_layout)
        layout.addWidget(port_group)

        sample_group = QGroupBox("Sample Settings")
        sample_layout = QVBoxLayout()

        self.load_button = QPushButton("Load WAV Sample")
        self.load_button.clicked.connect(self.load_sample)
        sample_layout.addWidget(self.load_button)

        self.base_note = QSpinBox()
        self.base_note.setRange(0, 127)
        self.base_note.setValue(60)
        self.base_note.setPrefix("Base Note (MIDI): ")
        sample_layout.addWidget(self.base_note)

        range_layout = QHBoxLayout()
        self.min_note = QSpinBox()
        self.min_note.setRange(0, 127)
        self.min_note.setValue(36)
        self.min_note.setPrefix("Min Note: ")
        range_layout.addWidget(self.min_note)

        self.max_note = QSpinBox()
        self.max_note.setRange(0, 127)
        self.max_note.setValue(84)
        self.max_note.setPrefix("Max Note: ")
        range_layout.addWidget(self.max_note)
        
        sample_layout.addLayout(range_layout)

        self.process_button = QPushButton("Process Sample")
        self.process_button.clicked.connect(self.process_sample)
        sample_layout.addWidget(self.process_button)

        sample_group.setLayout(sample_layout)
        layout.addWidget(sample_group)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.test_sound_button = QPushButton("Test Sound (Middle C)")
        self.test_sound_button.clicked.connect(self.test_sound)
        layout.addWidget(self.test_sound_button)

        layout.addStretch()

    def setup_wave_gui(self, layout):
        self.wave_view = QGraphicsView()
        self.wave_scene = QGraphicsScene()
        self.wave_view.setScene(self.wave_scene)
        self.wave_view.setMinimumHeight(150)
        layout.addWidget(self.wave_view)

        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        
        left_scroll = QScrollArea()
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        self.sliders = {}

        param_groups = {
            'Wave': ['wave_mix', 'frequency'],
            'Modulation': ['freq_mod', 'freq_mod_rate', 'amp_mod', 'amp_mod_rate'],
            'Harmonics': [f'harm{i}_weight' for i in range(1, 6)],
            'ADSR': ['attack_time', 'decay_time', 'sustain_level', 'release_time'],
            'Effects': ['vibrato_rate', 'vibrato_depth', 'tremolo_rate', 'tremolo_depth', 
                        'distortion', 'noise_level', 'bit_crush', 'fold_amount'],
            'Filter': ['filter_cutoff', 'filter_resonance'],
            'Chorus': ['chorus_depth', 'chorus_rate']
        }

        for group_name, params in param_groups.items():
            group = QGroupBox(group_name)
            group_layout = QVBoxLayout()
            for param in params:
                slider_layout = QHBoxLayout()
                label = QLabel(param)
                slider = QSlider(Qt.Orientation.Horizontal)
                slider.setRange(0, 100 if any(x in param for x in ['weight', 'level', 'depth', 'mix', 'amount']) else 
                                200 if 'time' in param else 2000 if 'freq' in param or 'rate' in param else 100)
                slider.setValue(int(self.params[param] * (100 if any(x in param for x in ['weight', 'level', 'depth', 'mix', 'amount']) else 
                                                        100 if 'time' in param else 1)))
                slider.valueChanged.connect(lambda val, p=param: self.update_param(p, val))
                slider_layout.addWidget(label)
                slider_layout.addWidget(slider)
                group_layout.addLayout(slider_layout)
                self.sliders[param] = slider
            group.setLayout(group_layout)
            left_layout.addWidget(group)
        left_layout.addStretch()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        control_layout.addWidget(left_scroll)

        right_layout = QVBoxLayout()

        wave_group = QGroupBox("Wave Shapes")
        wave_layout = QVBoxLayout()
        self.wave1_radios = {}
        self.wave2_radios = {}
        for i, shape in enumerate(self.wave_shapes.keys()):
            radio1 = QRadioButton(shape + " (1)")
            radio1.toggled.connect(lambda checked, s=shape: self.update_wave_shape1(s) if checked else None)
            self.wave1_radios[shape] = radio1
            wave_layout.addWidget(radio1)
            if shape == 'sine':
                radio1.setChecked(True)
            radio2 = QRadioButton(shape + " (2)")
            radio2.toggled.connect(lambda checked, s=shape: self.update_wave_shape2(s) if checked else None)
            self.wave2_radios[shape] = radio2
            wave_layout.addWidget(radio2)
            if shape == 'sine' and i == 1:
                radio2.setChecked(True)
        wave_group.setLayout(wave_layout)
        right_layout.addWidget(wave_group)

        preset_group = QGroupBox("Presets")
        preset_layout = QVBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.currentTextChanged.connect(self.load_preset)
        preset_layout.addWidget(self.preset_combo)
        
        self.preset_name_edit = QLineEdit("NewPreset")
        preset_layout.addWidget(self.preset_name_edit)
        
        save_preset_btn = QPushButton("Save Preset")
        save_preset_btn.clicked.connect(self.save_preset)
        preset_layout.addWidget(save_preset_btn)
        
        random_btn = QPushButton("Randomize")
        random_btn.clicked.connect(self.randomize_params)
        preset_layout.addWidget(random_btn)
        
        export_btn = QPushButton("Export Presets")
        export_btn.clicked.connect(self.export_presets)
        preset_layout.addWidget(export_btn)
        
        import_btn = QPushButton("Import Presets")
        import_btn.clicked.connect(self.import_presets)
        preset_layout.addWidget(import_btn)
        
        preset_group.setLayout(preset_layout)
        right_layout.addWidget(preset_group)

        play_btn = QPushButton("Play")
        play_btn.clicked.connect(self.play_sound)
        loop_btn = QPushButton("Loop Play")
        loop_btn.clicked.connect(self.toggle_loop)
        save_wave_btn = QPushButton("Save WAV")
        save_wave_btn.clicked.connect(self.save_wave)
        right_layout.addWidget(play_btn)
        right_layout.addWidget(loop_btn)
        right_layout.addWidget(save_wave_btn)
        right_layout.addStretch()
        control_layout.addLayout(right_layout)

        layout.addWidget(control_widget)
        self.update_waveform()

    # Main Tab Methods
    def update_pianoroll(self, size=None):
        self.pianoroll_scene.clear()
        width = self.pianoroll_view.width()
        height = 100
        
        size = self.pianoroll_size_combo.currentText()
        if size == "1 Octave":
            keys = 12
            start_note = 60  # C4
        elif size == "3 Octaves":
            keys = 36
            start_note = 48  # C3
        else:  # 5 Octaves
            keys = 61
            start_note = 36  # C2
        
        key_width = width / keys
        
        for i in range(keys):
            note = start_note + i
            is_black = note % 12 in [1, 3, 6, 8, 10]
            x = i * key_width
            rect = QRectF(x, 0, key_width, height * (0.6 if is_black else 1.0))
            color = QColor(Qt.GlobalColor.black) if is_black else QColor(Qt.GlobalColor.white)
            item = self.pianoroll_scene.addRect(rect, QPen(Qt.GlobalColor.gray), color)
            item.setData(0, note)
        self.pianoroll_view.setSceneRect(0, 0, width, height)

    def pianoroll_mouse_press(self, event):
        item = self.pianoroll_scene.itemAt(event.scenePos(), self.pianoroll_view.transform())
        if item:
            note = item.data(0)
            if note in self.processed_sounds:
                self.play_note(note, 100)
                self.debug_label.setText(f"Pianoroll: Played note {note}")

    def load_main_preset(self, name):
        if name in self.presets:
            self.params = self.presets[name].copy()
            self.current_preset_name = name
            self.params.setdefault('wave_shape1', 'sine')
            self.params.setdefault('wave_shape2', 'sine')
            self.params.setdefault('frequency', 440.0)
            self.debug_label.setText(f"Loaded preset: {name}")
            self.background_timer.singleShot(100, self.background_process_preset)

    def background_process_preset(self):
        self.process_preset()
        self.save_preset_to_wav()

    def process_preset(self):
        if not self.current_preset_name or self.current_preset_name not in self.presets:
            self.debug_label.setText("Please select a preset first")
            return

        try:
            self.processed_sounds.clear()
            base_freq = self.params.get('frequency', 440.0)
            total_notes = self.max_note.value() - self.min_note.value() + 1
            self.progress.setMaximum(total_notes)
            self.progress.setValue(0)

            for note in range(self.min_note.value(), self.max_note.value() + 1):
                target_freq = 440 * (2 ** ((note - 69) / 12))
                self.params['frequency'] = target_freq
                wave = self.generate_wave()
                wave_stereo = np.vstack((wave, wave)).T.astype(np.float32)
                wave_int16 = np.int16(wave_stereo * 32767).copy(order='C')
                
                try:
                    sound = pygame.mixer.Sound(wave_int16)
                    self.processed_sounds[note] = sound
                except Exception as e:
                    self.debug_label.setText(f"Error creating sound for note {note}: {str(e)}")
                    continue

                self.progress.setValue(note - self.min_note.value() + 1)
                QApplication.processEvents()

            self.debug_label.setText(f"Processed {len(self.processed_sounds)} notes from preset '{self.current_preset_name}'\n"
                                     f"Range: {self.min_note.value()} to {self.max_note.value()}")
            self.params['frequency'] = base_freq
        except Exception as e:
            self.debug_label.setText(f"Error processing preset: {str(e)}")

    def save_preset_to_wav(self):
        if not self.current_preset_name or self.current_preset_name not in self.presets:
            self.debug_label.setText("Please select a preset first")
            return
        wave = self.generate_wave()
        wave_stereo = np.vstack((wave, wave)).T.astype(np.float32)
        wave_int16 = np.int16(wave_stereo * 32767).copy(order='C')
        filename = f"preset_{self.current_preset_name}_{self.params.get('frequency', 440.0)}Hz.wav"
        wavfile.write(filename, self.sample_rate, wave_int16)
        self.debug_label.setText(f"Saved preset to {filename}")

    # MIDI Methods
    def test_sound(self):
        note = 60
        if note in self.processed_sounds:
            sound = self.processed_sounds[note]
            sound.play()
            self.debug_label.setText(f"Playing test sound for note {note}")
        else:
            self.debug_label.setText(f"No processed sound for note {note}")

    def get_available_midi_ports(self):
        self.midi_port_selector.clear()
        midi_in = rtmidi.MidiIn()
        ports = midi_in.get_ports()
        
        if not ports:
            self.midi_debug.setText("No MIDI input ports found")
            return
            
        self.midi_port_selector.addItems(ports)
        self.midi_debug.setText(f"Available MIDI ports: {', '.join(ports)}")

    def select_midi_input(self):
        if self.midi_in:
            self.midi_in.close_port()

        try:
            self.midi_in = rtmidi.MidiIn()
            port_name = self.midi_port_selector.currentText()
            port_index = self.midi_port_selector.currentIndex()
            self.midi_in.open_port(port_index)
            self.midi_in.set_callback(self.midi_callback)
            self.midi_debug.setText(f"Connected to MIDI port: {port_name}")
        except Exception as e:
            self.midi_debug.setText(f"Error opening MIDI port: {str(e)}")

    def load_sample(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Load WAV Sample", "", "WAV Files (*.wav);;All Files (*)"
        )
        if file_name:
            try:
                sample_rate, audio_data = wavfile.read(file_name)
                if len(audio_data.shape) > 1:
                    audio_data = np.mean(audio_data, axis=1)

                audio_data = audio_data.astype(np.float32)
                audio_data /= np.max(np.abs(audio_data))

                self.base_sample = {
                    'path': file_name,
                    'rate': sample_rate,
                    'data': audio_data
                }
                
                self.sample_debug.setText(f"Loaded sample: {os.path.basename(file_name)}\n"
                                          f"Sample rate: {sample_rate}Hz\n"
                                          f"Length: {len(audio_data)} samples")
            except Exception as e:
                self.sample_debug.setText(f"Error loading sample: {str(e)}")

    def process_sample(self):
        if not self.base_sample:
            self.sample_debug.setText("Please load a sample first")
            return

        try:
            self.processed_sounds.clear()
            base_freq = 440 * (2 ** ((self.base_note.value() - 69) / 12))
            total_notes = self.max_note.value() - self.min_note.value() + 1
            self.progress.setMaximum(total_notes)
            self.progress.setValue(0)

            for note in range(self.min_note.value(), self.max_note.value() + 1):
                target_freq = 440 * (2 ** ((note - 69) / 12))
                pitch_ratio = target_freq / base_freq
                
                original_length = len(self.base_sample['data'])
                new_length = int(original_length / pitch_ratio)
                
                resampled = signal.resample(self.base_sample['data'], new_length)
                audio_int16 = np.int16(resampled * 32767)
                
                try:
                    sound = pygame.mixer.Sound(audio_int16)
                    self.processed_sounds[note] = sound
                except Exception as e:
                    self.sample_debug.setText(f"Error creating sound for note {note}: {str(e)}")
                    continue

                self.progress.setValue(note - self.min_note.value() + 1)
                QApplication.processEvents()

            self.sample_debug.setText(f"Processed {len(self.processed_sounds)} notes\n"
                                      f"Range: {self.min_note.value()} to {self.max_note.value()}")
        except Exception as e:
            self.sample_debug.setText(f"Error processing sample: {str(e)}")

    def update_volume(self):
        master_volume = self.volume_slider.value() / 100.0
        for sound in self.processed_sounds.values():
            sound.set_volume(master_volume)

    def midi_callback(self, message, time_stamp=None):
        if not message or len(message[0]) < 3:
            return

        status = message[0][0]
        note = message[0][1]
        velocity = message[0][2]
        channel = status & 0x0F

        self.note_debug.setText(f"MIDI event: status={hex(status)}, channel={channel}, note={note}, velocity={velocity}")

        if (0x90 <= status <= 0x9F or status == 0x98) and velocity > 0:
            self.play_note(note, velocity)
        elif (0x80 <= status <= 0x8F or (status == 0x98 and velocity == 0)):
            self.stop_note(note)

    def play_note(self, note, velocity):
        if note in self.processed_sounds:
            try:
                volume = (velocity / 127) * (self.volume_slider.value() / 100)
                channel = pygame.mixer.find_channel()
                if channel:
                    sound = self.processed_sounds[note]
                    sound.set_volume(volume)
                    channel.play(sound)
                    self.active_notes[note] = channel
                    self.note_debug.setText(f"Playing note: {note} (velocity: {velocity})")
                else:
                    self.note_debug.setText("No free channels available")
            except Exception as e:
                self.note_debug.setText(f"Error playing note {note}: {str(e)}")

    def stop_note(self, note):
        if note in self.active_notes:
            try:
                channel = self.active_notes[note]
                channel.stop()
                del self.active_notes[note]
                self.note_debug.setText(f"Stopped note: {note}")
            except Exception as e:
                self.note_debug.setText(f"Error stopping note {note}: {str(e)}")

    # Wave Generator Methods
    def custom_wave(self, t, freq):
        # Uproszczona wersja bez custom_paramX: mieszanka sinusoidy i szumu
        return 0.7 * np.sin(2 * np.pi * freq * t) + 0.3 * np.random.normal(0, 1, len(t))

    def generate_wave(self):
        freq = self.params.get('frequency', 440.0)
        wave1 = self.wave_shapes[self.params.get('wave_shape1', 'sine')](self.t, freq)
        wave2 = self.wave_shapes[self.params.get('wave_shape2', 'sine')](self.t, freq)
        wave = wave1 * (1 - self.params.get('wave_mix', 0.5)) + wave2 * self.params.get('wave_mix', 0.5)

        for i in range(1, 6):
            weight = self.params.get(f'harm{i}_weight', 1.0 / (2 ** (i - 1)))
            wave += weight * np.sin(2 * np.pi * freq * i * self.t)

        if self.params.get('freq_mod', 0.0) > 0:
            fm = self.params['freq_mod'] * np.sin(2 * np.pi * self.params.get('freq_mod_rate', 0.0) * self.t)
            wave = np.sin(2 * np.pi * (freq + fm) * self.t)
        if self.params.get('amp_mod', 0.0) > 0:
            am = 1 + self.params['amp_mod'] * np.sin(2 * np.pi * self.params.get('amp_mod_rate', 0.0) * self.t)
            wave *= am

        if self.params.get('vibrato_depth', 0.0) > 0:
            vibrato = self.params['vibrato_depth'] * np.sin(2 * np.pi * self.params.get('vibrato_rate', 0.0) * self.t)
            wave = np.sin(2 * np.pi * freq * self.t + vibrato)
        if self.params.get('tremolo_depth', 0.0) > 0:
            tremolo = 1 + self.params['tremolo_depth'] * np.sin(2 * np.pi * self.params.get('tremolo_rate', 0.0) * self.t)
            wave *= tremolo
        if self.params.get('noise_level', 0.0) > 0:
            wave += np.random.normal(0, self.params['noise_level'], len(wave))
        if self.params.get('distortion', 0.0) > 0:
            wave = np.tanh(wave * (1 + self.params['distortion'] * 10))
        if self.params.get('bit_crush', 0.0) > 0:
            levels = 2 ** (16 - int(self.params['bit_crush'] * 14))
            wave = np.round(wave * levels) / levels
        if self.params.get('fold_amount', 0.0) > 0:
            wave = np.sin(wave * np.pi * self.params['fold_amount'])
        if self.params.get('filter_cutoff', 20000) < 20000:
            b, a = signal.butter(2, self.params['filter_cutoff'] / (self.sample_rate / 2), btype='low')
            wave = signal.filtfilt(b, a, wave)
        if self.params.get('chorus_depth', 0.0) > 0:
            delay = 0.03 * self.params['chorus_depth']
            delayed_wave = np.interp(self.t - delay, self.t, wave, left=0, right=0)
            wave += delayed_wave * self.params.get('chorus_rate', 0.0)

        wave *= self.apply_adsr()
        return wave / np.max(np.abs(wave))

    def apply_adsr(self):
        length = len(self.t)
        attack_samples = int(self.params.get('attack_time', 0.1) * self.sample_rate)
        decay_samples = int(self.params.get('decay_time', 0.2) * self.sample_rate)
        release_samples = int(self.params.get('release_time', 0.3) * self.sample_rate)
        total_envelope_samples = attack_samples + decay_samples + release_samples

        if total_envelope_samples > length:
            scale_factor = length / total_envelope_samples
            attack_samples = int(attack_samples * scale_factor)
            decay_samples = int(decay_samples * scale_factor)
            release_samples = int(release_samples * scale_factor)
            total_envelope_samples = attack_samples + decay_samples + release_samples

        sustain_samples = max(0, length - total_envelope_samples)

        attack = np.linspace(0, 1, attack_samples) if attack_samples > 0 else np.array([])
        decay = np.linspace(1, self.params.get('sustain_level', 0.7), decay_samples) if decay_samples > 0 else np.array([])
        sustain = np.ones(sustain_samples) * self.params.get('sustain_level', 0.7) if sustain_samples > 0 else np.array([])
        release = np.linspace(self.params.get('sustain_level', 0.7), 0, release_samples) if release_samples > 0 else np.array([])

        envelope = np.concatenate([attack, decay, sustain, release])
        if len(envelope) < length:
            envelope = np.pad(envelope, (0, length - len(envelope)), mode='constant')
        elif len(envelope) > length:
            envelope = envelope[:length]

        return envelope

    def update_param(self, param, value):
        scale = 1.0 if 'freq' in param or 'rate' in param else 0.01 if any(x in param for x in ['time', 'depth', 'level', 'mix', 'amount']) else 1.0
        self.params[param] = value * scale
        self.update_waveform()

    def update_wave_shape1(self, shape):
        self.params['wave_shape1'] = shape
        self.update_waveform()

    def update_wave_shape2(self, shape):
        self.params['wave_shape2'] = shape
        self.update_waveform()

    def randomize_params(self):
        for param in self.params:
            if param in ['wave_shape1', 'wave_shape2']:
                self.params[param] = random.choice(list(self.wave_shapes.keys()))
            else:
                max_val = 1.0 if any(x in param for x in ['weight', 'level', 'depth', 'mix', 'amount']) else \
                          2.0 if 'time' in param else 2000 if 'freq' in param or 'rate' in param else 1.0
                self.params[param] = random.uniform(0, max_val)
                if param in self.sliders:
                    scale = 100 if any(x in param for x in ['weight', 'level', 'depth', 'mix', 'amount']) else \
                            100 if 'time' in param else 1
                    self.sliders[param].setValue(int(self.params[param] * scale))
        self.update_waveform()

    def update_preset_lists(self):
        self.preset_combo.clear()
        self.preset_combo.addItems(self.presets.keys())
        self.main_preset_combo.clear()
        self.main_preset_combo.addItems(self.presets.keys())
        if self.current_preset_name in self.presets:
            self.preset_combo.setCurrentText(self.current_preset_name)
            self.main_preset_combo.setCurrentText(self.current_preset_name)

    def save_preset(self):
        name = self.preset_name_edit.text()
        if name:
            self.presets[name] = self.params.copy()
            self.current_preset_name = name
            self.update_preset_lists()
            preset_dir = "presets"
            os.makedirs(preset_dir, exist_ok=True)
            with open(os.path.join(preset_dir, f"{name}.json"), 'w') as f:
                json.dump(self.params, f, indent=4)

    def load_preset(self, name):
        if name in self.presets and not self.updating_waveform:
            self.updating_waveform = True
            self.params = self.presets[name].copy()
            self.current_preset_name = name
            self.params.setdefault('wave_shape1', 'sine')
            self.params.setdefault('wave_shape2', 'sine')
            self.params.setdefault('frequency', 440.0)
            for param, value in self.params.items():
                if param in self.sliders:
                    scale = 100 if any(x in param for x in ['weight', 'level', 'depth', 'mix', 'amount']) else \
                            100 if 'time' in param else 1
                    self.sliders[param].setValue(int(value * scale))
            self.update_waveform()
            self.update_preset_lists()
            self.updating_waveform = False

    def load_presets_from_directory(self):
        preset_dir = "presets"
        if os.path.exists(preset_dir):
            for filename in os.listdir(preset_dir):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(preset_dir, filename), 'r') as f:
                            preset_name = os.path.splitext(filename)[0]
                            self.presets[preset_name] = json.load(f)
                    except Exception as e:
                        print(f"Error loading preset {filename}: {str(e)}")
        self.update_preset_lists()

    def export_presets(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export Presets", "", "JSON Files (*.json)")
        if filename:
            with open(filename, 'w') as f:
                json.dump(self.presets, f, indent=4)
            print(f"Presets exported to {filename}")

    def import_presets(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Presets", "", "JSON Files (*.json)")
        if filename:
            with open(filename, 'r') as f:
                self.presets.update(json.load(f))
            self.update_preset_lists()
            print(f"Presets imported from {filename}")

    def update_waveform(self):
        if self.updating_waveform:
            return
        self.updating_waveform = True
        wave = self.generate_wave()
        self.wave_scene.clear()
        width = self.wave_view.width()
        height = 150
        samples = wave[:min(2000, len(wave))]
        step = width / len(samples)

        self.wave_scene.addLine(0, height / 2, width, height / 2, QPen(Qt.GlobalColor.gray))
        self.wave_scene.addLine(0, 0, 0, height, QPen(Qt.GlobalColor.gray))

        path = QPainterPath()
        path.moveTo(0, height / 2)
        for i, sample in enumerate(samples):
            x = i * step
            y = height / 2 - (sample * height / 2)
            path.lineTo(x, y)
        self.wave_scene.addPath(path, QPen(Qt.GlobalColor.blue, 1))

        self.play_line = self.wave_scene.addLine(0, 0, 0, height, QPen(Qt.GlobalColor.red, 2))
        self.wave_view.setSceneRect(0, 0, width, height)
        self.updating_waveform = False

    def update_play_position(self):
        if self.is_looping:
            self.play_position += 10 / (self.duration * 1000)
            if self.play_position >= 1:
                self.play_position = 0
            x = self.play_position * self.wave_view.width()
            self.play_line.setLine(x, 0, x, 150)

    def play_sound(self):
        wave = self.generate_wave()
        wave_stereo = np.vstack((wave, wave)).T.astype(np.float32)
        wave_int16 = np.int16(wave_stereo * 32767).copy(order='C')
        self.sound = pygame.mixer.Sound(wave_int16)
        self.sound.play()

    def toggle_loop(self):
        if not self.is_looping:
            self.start_loop()
            self.is_looping = True
            self.timer.start(10)
        else:
            self.stop_sound()
            self.is_looping = False
            self.timer.stop()
            self.play_position = 0
            self.update_waveform()

    def start_loop(self):
        wave = self.generate_wave()
        wave_stereo = np.vstack((wave, wave)).T.astype(np.float32)
        wave_int16 = np.int16(wave_stereo * 32767).copy(order='C')
        self.sound = pygame.mixer.Sound(wave_int16)
        self.sound.play(-1)

    def stop_sound(self):
        if self.sound:
            self.sound.stop()

    def save_wave(self):
        wave = self.generate_wave()
        wave_stereo = np.vstack((wave, wave)).T.astype(np.float32)
        wave_int16 = np.int16(wave_stereo * 32767).copy(order='C')
        filename = f"custom_wave_{self.params.get('frequency', 440.0)}Hz.wav"
        wavfile.write(filename, self.sample_rate, wave_int16)
        print(f"Saved to {filename}")

    def closeEvent(self, event):
        if self.midi_in:
            self.midi_in.close_port()
        pygame.mixer.quit()
        event.accept()

def main():
    app = QApplication(sys.argv)
    window = WavInstrumentApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
