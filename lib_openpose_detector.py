'''
Openpose detector class.
'''

import sys
import cv2
import os
from sys import platform
import argparse
import time
import numpy as np
from tempfile import TemporaryFile

if True:  # Import openpose
    OPENPOSE_PYTHONPATH = os.environ['OPENPOSE_PYTHONPATH']
    sys.path.append(OPENPOSE_PYTHONPATH)
    from openpose import pyopenpose as op
    ROOT = os.path.dirname(os.path.abspath(__file__))+'/'

''' -------------------------------------- Settings -------------------------------------- '''

OPENPOSE_HOME = os.environ['OPENPOSE_HOME'] + "/"
MODEL_PATH = OPENPOSE_HOME + "models/"

''' ------------------------------- Command line arguments ------------------------------- '''


class OpenposeDetector(object):
    def __init__(self):
        self._params = self._set_openpose_params()
        self._opWrapper = op.WrapperPython()
        self._opWrapper.configure(self._params)
        self._opWrapper.start()  # Start Openpose.

    def detect(self, color_image, is_return_joints=False):
        '''
        Arguments:
            color_image {image}: shape=[rows, cols, 3]; type=np.uint8.
        Return:
            datum {op.Datum()}: Detect results are stored here.
                datum.poseKeypoints {np.ndarray}:
                    shape = [P, N, 3]; type = np.float32.
                    P: Number of detected human bodies. 
                    N: N body joints defined by the detector model, such as COCO and MPI.
                    3: [pixel_column, pixel_row, confidence]. 
                        The not-detected joint has a [0., 0., 0.] value.
                datum.poseKeypoints {list}:
                    List length is 2, which are the left hand and the right hand.
                    Each element is a np.ndarray of shape = [P, M, 3]
                    P and 3 have the same meaning as `poseKeypoints`.
                    M: M body joints.
        For model definition, please see:
            https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/doc/output.md
        '''
        datum = op.Datum()
        datum.cvInputData = color_image
        self._opWrapper.emplaceAndPop([datum])
        # print("Body keypoints: \n" + str(datum.poseKeypoints))
        # print("Hand keypoints: \n" + str(datum.handKeypoints))
        if is_return_joints:
            body_joints = np.array(datum.poseKeypoints)
            hand_joints = np.array(datum.handKeypoints)
            np.swapaxes(hand_joints, 0, 1) # reshape to [P, 2, M, 3]
            return body_joints, hand_joints
        else:
            return datum

    def save_joints_positions(self, datum, pose_filename, hand_filename):
        ''' Save body and hand joints to two binary files. '''

        def save_binary(filename, data):
            np.save(filename, np.array(data))

        def save_txt(filename, data):
            np.savetxt(filename, np.array(data), delimiter=",")

        save_binary(pose_filename, datum.poseKeypoints)
        save_binary(hand_filename, datum.handKeypoints)

        # To load the data, use:
        # bodies_joints = np.load(pose_filename)
        # hands_joints = np.load(hand_filename)

    def _set_openpose_params(self, command_line_args=[]):
        ''' Custom openpose params.
        (Refer to $OPENPOSE_HOME/include/openpose/flags.hpp for more parameters.)
        '''
        params = dict()
        params["model_folder"] = MODEL_PATH
        params["face"] = False  # I haven't done this.
        params["hand"] = True
        params["net_resolution"] = "320x240"  # e.g.: "240x160"
        params["model_pose"] = "COCO"  # Please use "COCO".

        # Add others settings from command line arguments to `params`
        if command_line_args:
            args = command_line_args
            for i in range(0, len(args[1])):
                curr_item = args[1][i]
                if i != len(args[1])-1:
                    next_item = args[1][i+1]
                else:
                    next_item = "1"
                if "--" in curr_item and "--" in next_item:
                    key = curr_item.replace('-', '')
                    if key not in params:
                        params[key] = "1"
                elif "--" in curr_item and "--" not in next_item:
                    key = curr_item.replace('-', '')
                    if key not in params:
                        params[key] = next_item
        return params


def makedir(folder):
    folder = os.path.dirname(folder)
    if not os.path.exists(folder):
        os.makedirs(folder)


''' -------------------------------------- Unit Test -------------------------------------- '''


def test_openpose_on_images():
    # -- Settings.
    DST_FOLDER = ROOT + "output/"

    # -- Command line arguments.
    def parse_args():
        parser = argparse.ArgumentParser()
        parser.add_argument("--image_dir",
                            default=ROOT+"data/image1/",
                            help="Process a directory of images. "
                            "Read all standard formats (jpg, png, bmp, etc.).")
        args = parser.parse_known_args()
        return args

    args = parse_args()

    # -- Setup variables.
    detector = OpenposeDetector()
    makedir(DST_FOLDER)

    # -- Read images and detect.
    imagePaths = op.get_images_on_directory(args[0].image_dir)
    for i, imagePath in enumerate(imagePaths):
        t0 = time.time()

        # Read image.
        color_image = cv2.imread(imagePath)

        # Detect human skeletons.
        datum = detector.detect(color_image)
        print("Image {}/{}. Total time = {} seconds.".format(
            i+1, len(imagePaths), time.time()-t0))

        # Save.
        s = DST_FOLDER + "{:05d}".format(i) + "_"
        filename_body = s + "body_joints.npy"
        filename_hand = s + "hand_joints.npy"
        filename_image = s + "result.jpg"

        detector.save_joints_positions(
            datum, filename_body, filename_hand)

        image_with_skeletons_on_it = datum.cvOutputData
        cv2.imwrite(filename_image, image_with_skeletons_on_it)
        print("  Write results to: " + s)

        # Show.
        cv2.imshow("Detection Result", image_with_skeletons_on_it)
        key = cv2.waitKey(15)
        if key == 27:
            break


if __name__ == '__main__':
    test_openpose_on_images()
