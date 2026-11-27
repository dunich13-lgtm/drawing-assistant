;; Read-only geometry dumps. Plain AutoLISP only (no vl-*). Parsed by tools/geom.py (load).
;;   (bg-dump "BLOCKNAME" "C:/path/out.tsv")          every entity of one block definition (local coordinates)
;;   (geo-dump '("LAYER A" "LAYER B") "C:/path/out.tsv")  model-space entities on the listed layers (exact names)
;; Line format (tab-separated):  TYPE  layer  handle  data...
;;   LINE   x1,y1 x2,y2
;;   LWPOLYLINE closedflag  x,y,bulge x,y,bulge ...
;;   ARC    cx,cy r a0 a1          CIRCLE cx,cy r
;;   INSERT name x,y rot sx,sy
;;   HATCH  pattern  then raw boundary groups "code=value" until group 75
;;   TEXT/MTEXT x,y height text
;;   anything else: TYPE layer handle (reported as skipped by the parser)
;; A "~" after the type (e.g. LWPOLYLINE~) means the entity's extrusion is (0,0,-1): its coordinates are in a
;; mirrored OCS (x = -x). The parser converts them to world coordinates.
;; Comments must stay on their own lines: the runner strips them and sends one form at a time.
(defun bg-f (v) (rtos v 2 4))
(defun bg-p (p) (strcat (bg-f (car p)) "," (bg-f (cadr p))))
(defun bg-typ (ed / typ ex)
  (setq typ (cdr (assoc 0 ed)) ex (cdr (assoc 210 ed)))
  (if (and ex (member typ '("LWPOLYLINE" "ARC" "CIRCLE" "HATCH")) (< (caddr ex) 0.0)) (strcat typ "~") typ))
(defun bg-hatch (ed / s r on)
  (setq s (strcat "\t" (cdr (assoc 2 ed))) on nil)
  (foreach r ed
    (cond
      ((= (car r) 91) (setq on T))
      ((= (car r) 75) (setq on nil))
      ((and on (member (car r) '(10 11))) (setq s (strcat s "\t" (itoa (car r)) "=" (bg-p (cdr r)))))
      ((and on (member (car r) '(92 72 73 93 40 42 50 51)))
       (setq s (strcat s "\t" (itoa (car r)) "=" (if (= (type (cdr r)) 'INT) (itoa (cdr r)) (bg-f (cdr r))))))))
  s)
(defun bg-row (ed / typ s r)
  (setq typ (cdr (assoc 0 ed)))
  (if (not (member typ '("VERTEX" "SEQEND" "ATTRIB")))
    (progn
      (setq s (strcat (bg-typ ed) "\t" (cdr (assoc 8 ed)) "\t" (cdr (assoc 5 ed))))
      (cond
        ((= typ "LINE") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-p (cdr (assoc 11 ed))))))
        ((= typ "LWPOLYLINE")
         (setq s (strcat s "\t" (itoa (logand 1 (cdr (assoc 70 ed))))))
         (foreach r ed
           (if (= (car r) 10) (setq s (strcat s "\t" (bg-p (cdr r)))))
           (if (= (car r) 42) (setq s (strcat s "," (bg-f (cdr r)))))))
        ((= typ "ARC") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))) "\t" (bg-f (cdr (assoc 50 ed))) "\t" (bg-f (cdr (assoc 51 ed))))))
        ((= typ "CIRCLE") (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))))))
        ((= typ "INSERT") (setq s (strcat s "\t" (cdr (assoc 2 ed)) "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 50 ed))) "\t" (bg-f (cdr (assoc 41 ed))) "," (bg-f (cdr (assoc 42 ed))))))
        ((member typ '("TEXT" "MTEXT")) (setq s (strcat s "\t" (bg-p (cdr (assoc 10 ed))) "\t" (bg-f (cdr (assoc 40 ed))) "\t" (cdr (assoc 1 ed)))))
        ((= typ "HATCH") (setq s (strcat s (bg-hatch ed)))))
      s)))
(defun bg-dump (blk path / f e s)
  (setq f (open path "w" "utf8") e (cdr (assoc -2 (tblsearch "BLOCK" blk))))
  (while e
    (setq s (bg-row (entget e)))
    (if s (write-line s f))
    (setq e (entnext e)))
  (write-line "#DONE" f)
  (close f)
  (princ))
(defun geo-dump (lays path / f ss i ed s n)
  (setq f (open path "w" "utf8") n 0 ss (ssget "X" '((410 . "Model"))))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq ed (entget (ssname ss i)) i (1+ i))
        (if (member (cdr (assoc 8 ed)) lays)
          (progn (setq s (bg-row ed)) (if s (progn (write-line s f) (setq n (1+ n)))))))))
  (write-line (strcat "#DONE\t" (itoa n)) f)
  (close f)
  (princ (strcat "\nGeometry dump: " (itoa n) " entities written."))
  (princ))
