"""
Tracker module using Kalman Filter and SORT (Simple Online and Realtime Tracking).
Implement tracking algorithm from scratch without heavy dependencies like filterpy.
"""

import numpy as np
from scipy.optimize import linear_sum_assignment


class SimpleKalman:
    """A minimal 2D Kalman filter implementation for bounding box tracking."""
    
    def __init__(self, cx, cy, w, h):
        self.dt = 1.0  # Time step
        
        # State transitions (x, y, w, h, vx, vy, vw, vh)
        self.F = np.eye(8)
        for i in range(4):
            self.F[i, i+4] = self.dt
            
        self.H = np.eye(4, 8)  # Observation matrix: we only observe x, y, w, h
        
        # Initial state
        self.x = np.array([cx, cy, w, h, 0, 0, 0, 0], dtype=float).reshape(8, 1)
        
        # Covariance matrices
        self.P = np.eye(8) * 10.0
        self.P[4:, 4:] *= 1000.0  # Higher uncertainty for initial velocities
        
        self.R = np.eye(4) * 10.0  # Measurement noise
        
        self.Q = np.eye(8) * 0.01  # Process noise
        self.Q[4:, 4:] *= 0.01

    def predict(self):
        """Predict the next state."""
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(np.dot(self.F, self.P), self.F.T) + self.Q
        return self.x[:4].flatten()

    def update(self, z):
        """Update state using measurement z [cx, cy, w, h]."""
        z = np.array(z).reshape(4, 1)
        y = z - np.dot(self.H, self.x)
        S = np.dot(self.H, np.dot(self.P, self.H.T)) + self.R
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))
        
        self.x = self.x + np.dot(K, y)
        self.P = self.P - np.dot(K, np.dot(self.H, self.P))


class Track:
    """Represents a single tracked object."""
    
    _id_counter = 1
    
    def __init__(self, bbox):
        self.id = Track._id_counter
        Track._id_counter += 1
        
        x1, y1, x2, y2 = bbox
        cx, cy, w, h = (x1+x2)/2, (y1+y2)/2, x2-x1, y2-y1
        
        self.kf = SimpleKalman(cx, cy, w, h)
        self.time_since_update = 0
        self.hits = 1
        self.hit_streak = 1
        self.age = 1

    def predict(self):
        """Predict the next box for this track."""
        pred = self.kf.predict()
        self.age += 1
        self.time_since_update += 1
        self.hit_streak = 0
        return self.get_bbox()

    def update(self, bbox):
        """Update track with newly matched bounding box."""
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1
        x1, y1, x2, y2 = bbox
        cx, cy, w, h = (x1+x2)/2, (y1+y2)/2, x2-x1, y2-y1
        self.kf.update([cx, cy, w, h])

    def get_bbox(self):
        """Return the current bounding box [x1, y1, x2, y2]."""
        # Ensure w and h are positive
        x = self.kf.x[:4].flatten()
        cx, cy, w, h = x[0], x[1], max(1, x[2]), max(1, x[3])
        return [cx - w/2, cy - h/2, cx + w/2, cy + h/2]


class SORT:
    """
    SORT (Simple Online and Realtime Tracking) algorithm instance.
    Associates bounding boxes across frames using Hungarian algorithm + Kalman Filter.
    """
    
    def __init__(self, max_age=5, min_hits=3, iou_threshold=0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.tracks = []
        self.frame_count = 0

    def get_iou(self, box1, box2):
        """Compute Intersection over Union (IoU) between two bounding boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])
        
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        intersection = w * h
        a1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        a2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = a1 + a2 - intersection
        if union <= 0:
            return 0
        return intersection / union

    def associate_detections_to_trackers(self, detections, trackers):
        """Assign detections to existing tracks using Hungarian Algorithm."""
        if len(trackers) == 0:
            return np.empty((0, 2), dtype=int), np.arange(len(detections)), np.empty((0,), dtype=int)
            
        iou_matrix = np.zeros((len(detections), len(trackers)), dtype=np.float32)
        for d, det in enumerate(detections):
            for t, trk in enumerate(trackers):
                iou_matrix[d, t] = self.get_iou(det, trk)
                
        if min(iou_matrix.shape) > 0:
            a = (iou_matrix > self.iou_threshold).astype(np.int32)
            if a.sum(1).max() == 1 and a.sum(0).max() == 1:
                # Fast one-to-one mapping if possible
                matched_indices = np.stack(np.where(a), axis=1)
            else:
                row_ind, col_ind = linear_sum_assignment(-iou_matrix)
                matched_indices = np.stack([row_ind, col_ind], axis=1)
        else:
            matched_indices = np.empty(shape=(0, 2))
            
        unmatched_detections = []
        for d, det in enumerate(detections):
            if d not in matched_indices[:, 0]:
                unmatched_detections.append(d)
                
        unmatched_trackers = []
        for t, trk in enumerate(trackers):
            if t not in matched_indices[:, 1]:
                unmatched_trackers.append(t)
                
        # Filter matches below IoU threshold
        matches = []
        for m in matched_indices:
            if iou_matrix[m[0], m[1]] < self.iou_threshold:
                unmatched_detections.append(m[0])
                unmatched_trackers.append(m[1])
            else:
                matches.append(m.reshape(1, 2))
                
        if len(matches) == 0:
            matches = np.empty((0, 2), dtype=int)
        else:
            matches = np.concatenate(matches, axis=0)
            
        return matches, np.array(unmatched_detections), np.array(unmatched_trackers)

    def update(self, dets):
        """
        Update the tracker with new detections.
        
        Args:
            dets: numpy array of shape (N, 4+) containing [x1, y1, x2, y2, score, ...]
            
        Returns:
            numpy array of shape (M, 5) containing [x1, y1, x2, y2, track_id]
        """
        self.frame_count += 1
        
        # Predict
        trks = np.zeros((len(self.tracks), 4))
        to_del = []
        for i, trk in enumerate(self.tracks):
            pos = trk.predict()
            trks[i] = pos
            if np.any(np.isnan(pos)):
                to_del.append(i)
                
        for i in reversed(to_del):
            self.tracks.pop(i)
            trks = np.delete(trks, i, 0)
            
        # Associate
        matched, unmatched_dets, unmatched_trks = self.associate_detections_to_trackers(dets, trks)
        
        # Update matched
        for m in matched:
            self.tracks[m[1]].update(dets[m[0]][:4])
            
        # Create un-matched
        for i in unmatched_dets:
            self.tracks.append(Track(dets[i][:4]))
            
        # Compile result
        ret = []
        for trk in self.tracks:
            # Return active tracks that have been seen enough times
            if trk.time_since_update <= 2 and (trk.hits >= self.min_hits or self.frame_count <= self.min_hits):
                bbox = trk.get_bbox()
                ret.append([bbox[0], bbox[1], bbox[2], bbox[3], trk.id])
                
        # Cleanup old tracks
        i = len(self.tracks)
        for trk in reversed(self.tracks):
            i -= 1
            if trk.time_since_update > self.max_age:
                self.tracks.pop(i)
                
        return np.array(ret) if len(ret) > 0 else np.empty((0, 5))
