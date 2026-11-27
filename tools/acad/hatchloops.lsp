;; Read-only: boundary paths of every HATCH on the given layer(s) (wildcards ok, e.g. "A-WALL*").
;; Output lines:  H handle pattern truecolor  |  P (new path)  |  10 x y / 11 x y (path vertices / edge points)
;; Call: (hl-dump "A-WALL*" "C:/path/out.txt")
;; Comments must stay on their own lines: the runner strips them before sending the code inline.
(defun hl-dump (lay path / ss i e ed f inpath rec col)
  (setq ss (ssget "X" (list '(0 . "HATCH") (cons 8 lay))))
  (setq f (open path "w" "utf8"))
  (if ss
    (progn
      (setq i 0)
      (repeat (sslength ss)
        (setq e (ssname ss i) ed (entget e) inpath nil)
        (setq col (cdr (assoc 420 ed)))
        (write-line (strcat "H " (cdr (assoc 5 ed)) " " (cdr (assoc 2 ed)) " " (if col (itoa col) "0")) f)
        (foreach rec ed
          (cond
            ((= (car rec) 92) (setq inpath T) (write-line "P" f))
            ((= (car rec) 75) (setq inpath nil))
            ((and inpath (member (car rec) '(10 11)))
             (write-line (strcat (itoa (car rec)) " " (rtos (cadr rec) 2 6) " " (rtos (caddr rec) 2 6)) f))))
        (setq i (1+ i)))))
  (write-line "#DONE" f)
  (close f)
  (princ (strcat "\nHatch loops: " (if ss (itoa (sslength ss)) "0") " hatches written."))
  (princ))
