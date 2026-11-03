import { configure } from "@testing-library/react";

// The first run after a change can be slow, and the default wait of 1 s failed twice on that alone.
configure({ asyncUtilTimeout: 5000 });

// jsdom does not implement the dialog methods.
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
  this.dispatchEvent(new Event("close"));
};
